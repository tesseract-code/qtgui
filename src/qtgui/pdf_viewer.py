"""
PDF Viewer — built with PyQt6 + PyMuPDF (fitz)

Features
--------
* Open any PDF via File menu or Ctrl+O
* Page navigation  (Prev / Next / jump-to-page)
* Zoom  (In / Out / Fit-Width / Fit-Page  +  Ctrl+scroll)
* Continuous scroll through the whole document
* Thumbnail panel on the left for quick page jumps
* Drag-to-pan when zoomed in
* Dark-friendly UI
"""

import sys

import fitz  # PyMuPDF
from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QSize)
from PyQt6.QtGui import (QImage, QPixmap, QAction, QKeySequence,
                         QIcon, QWheelEvent,
                         QCursor)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QScrollArea, QLabel, QToolBar, QStatusBar,
    QFileDialog,
    QSpinBox, QSizePolicy, QListWidget, QListWidgetItem,
    QSplitter, QWidget, QVBoxLayout, QMenuBar, )


# ── helpers ────────────────────────────────────────────────────────────────

def _fitz_page_to_qpixmap(page: fitz.Page, zoom: float) -> QPixmap:
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = QImage(pix.samples, pix.width, pix.height,
                 pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(img)


# ── thumbnail loader (background thread) ───────────────────────────────────

class ThumbnailLoader(QThread):
    thumbnail_ready = pyqtSignal(int, QPixmap)

    def __init__(self, doc: fitz.Document):
        super().__init__()
        self._doc = doc
        self._stop = False

    def stop(self):
        self._stop = True
        self.wait()

    def run(self):
        for i in range(len(self._doc)):
            if self._stop:
                break
            pix = _fitz_page_to_qpixmap(self._doc[i], zoom=0.2)
            self.thumbnail_ready.emit(i, pix)


# ── zoomable / pannable page label ─────────────────────────────────────────

class PageLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drag_pos = None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, ev):
        if self._drag_pos is not None:
            delta = ev.globalPosition().toPoint() - self._drag_pos
            self._drag_pos = ev.globalPosition().toPoint()
            sa = self.parent().parent()  # QScrollArea
            if isinstance(sa, QScrollArea):
                sb = sa.horizontalScrollBar()
                sb.setValue(sb.value() - delta.x())
                sb = sa.verticalScrollBar()
                sb.setValue(sb.value() - delta.y())

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))


# ── main window ────────────────────────────────────────────────────────────

class PDFViewer(QWidget):
    ZOOM_STEP = 0.15
    ZOOM_MIN = 0.25
    ZOOM_MAX = 5.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Viewer")
        self.resize(1100, 820)

        self._doc: fitz.Document | None = None
        self._page = 0
        self._zoom = 1.0
        self._thumb_loader: ThumbnailLoader | None = None

        self._build_ui()
        self._update_ui_state()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # --- menu bar (as a plain widget) ---
        self._menu_bar = QMenuBar()
        self._build_menu(self._menu_bar)
        main_layout.addWidget(self._menu_bar)

        # --- toolbar (as a plain widget) ---
        self._toolbar = QToolBar("Main")
        self._build_toolbar(self._toolbar)
        main_layout.addWidget(self._toolbar)

        # --- left: thumbnail list ---
        self._thumb_list = QListWidget()
        self._thumb_list.setFixedWidth(140)
        self._thumb_list.setIconSize(QSize(110, 150))
        self._thumb_list.setSpacing(4)
        self._thumb_list.currentRowChanged.connect(self._on_thumb_clicked)

        # --- right: scroll area with the page label ---
        self._page_label = PageLabel()
        self._page_label.setSizePolicy(QSizePolicy.Policy.Expanding,
                                       QSizePolicy.Policy.Expanding)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._page_label)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidgetResizable(False)
        self._scroll.setStyleSheet("background:#404040;")
        self._scroll.wheelEvent = self._scroll_wheel

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._thumb_list)
        splitter.addWidget(self._scroll)
        splitter.setStretchFactor(0, 1)   # optional
        main_layout.addWidget(splitter, stretch=1)

        # --- status bar (as a plain widget) ---
        self._status_bar = QStatusBar()
        main_layout.addWidget(self._status_bar)

    def _build_menu(self, mb: QMenuBar):
        file = mb.addMenu("&File")

        open_act = QAction("&Open…", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self.open_file)
        file.addAction(open_act)

        file.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        quit_act.triggered.connect(self.close)
        file.addAction(quit_act)

        view = mb.addMenu("&View")
        zi = QAction("Zoom &In", self)
        zi.setShortcut("Ctrl++")
        zi.triggered.connect(self.zoom_in)
        view.addAction(zi)
        zo = QAction("Zoom &Out", self)
        zo.setShortcut("Ctrl+-")
        zo.triggered.connect(self.zoom_out)
        view.addAction(zo)
        zf = QAction("Fit &Width", self)
        zf.setShortcut("Ctrl+W")
        zf.triggered.connect(self.zoom_fit_width)
        view.addAction(zf)
        zp = QAction("Fit &Page", self)
        zp.setShortcut("Ctrl+Shift+W")
        zp.triggered.connect(self.zoom_fit_page)
        view.addAction(zp)

    def _build_toolbar(self, tb: QToolBar):
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        def act(label, slot, shortcut=None, tip=None):
            a = QAction(label, self)
            if shortcut: a.setShortcut(shortcut)
            if tip:      a.setToolTip(tip)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        self._act_open = act("📂 Open", self.open_file, "Ctrl+O")
        tb.addSeparator()
        self._act_prev = act("◀ Prev", self.prev_page, "Left")
        self._act_next = act("▶ Next", self.next_page, "Right")

        # page spin
        self._page_spin = QSpinBox()
        self._page_spin.setMinimum(1)
        self._page_spin.setMaximum(1)
        self._page_spin.setFixedWidth(60)
        self._page_spin.valueChanged.connect(self._on_spin_changed)
        tb.addWidget(self._page_spin)

        self._total_label = QLabel(" / 0 ")
        tb.addWidget(self._total_label)
        tb.addSeparator()

        act("🔍+", self.zoom_in, "Ctrl+=", "Zoom In")
        act("🔍-", self.zoom_out, "Ctrl+-", "Zoom Out")
        act("↔ Fit Width", self.zoom_fit_width, "Ctrl+W")
        act("⛶ Fit Page", self.zoom_fit_page, "Ctrl+Shift+W")

        # zoom percentage label
        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(55)
        tb.addWidget(self._zoom_label)

    # ── file open ──────────────────────────────────────────────────────────

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf);;All Files (*)")
        if path:
            self._load(path)

    def _load(self, path: str):
        if self._thumb_loader:
            self._thumb_loader.stop()
            self._thumb_loader = None

        if self._doc:
            self._doc.close()

        self._doc = fitz.open(path)
        self._page = 0
        self._zoom = 1.0

        n = len(self._doc)
        self._page_spin.setMaximum(n)
        self._page_spin.setValue(1)
        self._total_label.setText(f" / {n}")
        self.setWindowTitle(f"PDF Viewer — {path.split('/')[-1]}")

        self._thumb_list.clear()
        for i in range(n):
            item = QListWidgetItem(f"  {i + 1}")
            item.setSizeHint(QSize(130, 160))
            self._thumb_list.addItem(item)

        self._thumb_loader = ThumbnailLoader(self._doc)
        self._thumb_loader.thumbnail_ready.connect(self._on_thumb_ready)
        self._thumb_loader.start()

        self._render_page()
        self._update_ui_state()

    # ── rendering ──────────────────────────────────────────────────────────

    def _render_page(self):
        if self._doc is None:
            return
        pix = _fitz_page_to_qpixmap(self._doc[self._page], self._zoom)
        self._page_label.setPixmap(pix)
        self._page_label.resize(pix.size())
        self._zoom_label.setText(f"{int(self._zoom * 100)}%")
        self._status_bar.showMessage(                              # <-- changed
            f"Page {self._page + 1} of {len(self._doc)}  •  "
            f"Zoom {int(self._zoom * 100)}%")

    # ── navigation ─────────────────────────────────────────────────────────

    def prev_page(self):
        if self._doc and self._page > 0:
            self._page -= 1
            self._sync_spin()
            self._render_page()

    def next_page(self):
        if self._doc and self._page < len(self._doc) - 1:
            self._page += 1
            self._sync_spin()
            self._render_page()

    def _on_spin_changed(self, val):
        if self._doc and val - 1 != self._page:
            self._page = val - 1
            self._thumb_list.setCurrentRow(self._page)
            self._render_page()

    def _on_thumb_clicked(self, row):
        if self._doc and row != self._page and row >= 0:
            self._page = row
            self._sync_spin()
            self._render_page()

    def _sync_spin(self):
        self._page_spin.blockSignals(True)
        self._page_spin.setValue(self._page + 1)
        self._page_spin.blockSignals(False)
        self._thumb_list.setCurrentRow(self._page)

    # ── zoom ───────────────────────────────────────────────────────────────

    def zoom_in(self):
        self._set_zoom(self._zoom + self.ZOOM_STEP)

    def zoom_out(self):
        self._set_zoom(self._zoom - self.ZOOM_STEP)

    def zoom_fit_width(self):
        if self._doc is None:
            return
        page = self._doc[self._page]
        avail = self._scroll.viewport().width() - 20
        self._set_zoom(avail / page.rect.width)

    def zoom_fit_page(self):
        if self._doc is None:
            return
        page = self._doc[self._page]
        zw = (self._scroll.viewport().width() - 20) / page.rect.width
        zh = (self._scroll.viewport().height() - 20) / page.rect.height
        self._set_zoom(min(zw, zh))

    def _set_zoom(self, z: float):
        self._zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, z))
        self._render_page()

    # ── mouse-wheel (Ctrl = zoom, plain = scroll) ─────────────────────────

    def _scroll_wheel(self, ev: QWheelEvent):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl + wheel = zoom
            delta = ev.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
        else:
            # Plain wheel = page navigation
            delta = ev.angleDelta().y()
            if delta > 0:  # wheel up  → previous page (common behaviour)
                self.prev_page()
            else:  # wheel down → next page
                self.next_page()

    # ── thumbnails ─────────────────────────────────────────────────────────

    def _on_thumb_ready(self, index: int, pix: QPixmap):
        item = self._thumb_list.item(index)
        if item:
            item.setIcon(QIcon(pix))

    # ── misc ───────────────────────────────────────────────────────────────

    def _update_ui_state(self):
        loaded = self._doc is not None
        self._act_prev.setEnabled(loaded)
        self._act_next.setEnabled(loaded)
        self._page_spin.setEnabled(loaded)

    def closeEvent(self, ev):
        if self._thumb_loader:
            self._thumb_loader.stop()
        super().closeEvent(ev)

    def keyPressEvent(self, ev):
        key = ev.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self.next_page()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.prev_page()
        elif key == Qt.Key.Key_Home:
            if self._doc:
                self._page = 0;
                self._sync_spin();
                self._render_page()
        elif key == Qt.Key.Key_End:
            if self._doc:
                self._page = len(self._doc) - 1;
                self._sync_spin();
                self._render_page()
        else:
            super().keyPressEvent(ev)
