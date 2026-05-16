"""
workspace.py
------------
WorkspaceManager — a self-contained workspace widget that composes DockManager
with a code editor, image/video/PDF/3D viewers, directory browser, symbols
panel, and embedded terminal.

Layout persistence is handled entirely by WorkspaceLayoutManager (see
workspace_layout.py).  WorkspaceManager's only responsibilities toward
persistence are:

- Constructing a WorkspaceLayoutManager and wiring it up.
- Writing to ``layout_manager.dynamic_panels`` when a new file panel is opened.
- Exposing the thin public ``save_layout`` / ``restore_layout`` pass-throughs.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QUrl, Qt, QTimer, QObject, QEvent
from PyQt6.QtGui import QIcon, QPixmap, QSurfaceFormat, QDesktopServices
from PyQt6.QtWidgets import (
    QFrame, QStatusBar, QHBoxLayout, QMessageBox, QWidget, QMainWindow
)

from qtgui.dock.layout import WorkspaceLayoutManager
from image.gl.utils import get_surface_format
from image.gl_imshow import GLImageShow
from image.load.factory import Backend
from image.load.load import load_image
from pycore.files import FileExtensionCategory, FileInfo
from qtdisplay.dock.mngr import DockManager, DOCK_PANEL_ID_PROPERTY
from qtgui.file.code.editor import (CodeEditorWidget, CodeEditor,
                                    LANG_TO_SYMBOLS)
from qtgui.file.watch.widget import DirectoryWidget, build_file_info
from qtgui.pdf_viewer import PDFViewer
from qtgui.pixmap import colorize_pixmap
from qtgui.terminal.widget import TerminalWidget
from qtgui.video.playback import VideoPlaybackWidget
from qtgui.vtk_utils.viewer3D import ModelViewerWidget


try:
    from qtgui.file.code.symbols import SymbolsWidget

    _SYMBOLS_AVAILABLE = True
except ImportError:
    _SYMBOLS_AVAILABLE = False

# ── Stable IDs for the four always-alive panels ───────────────────────────────
_ID_EDITOR = "workspace:code-editor"
_ID_FILES = "workspace:file-tree"
_ID_SYMBOLS = "workspace:symbols"
_ID_TERMINAL = "workspace:terminal"


def _defer_until_shown(widget: QWidget, fn) -> None:
    """
    Call *fn* the first time *widget* receives a ``showEvent``.

    Defers work that requires an active GL context or a realised window
    surface (e.g. ``GLImageShow.set_data``, ``VideoPlaybackWidget.start``).
    Using ``QTimer.singleShot(0, fn)`` is not sufficient after a layout
    restore because the widget is constructed before being embedded in the
    dock, so the timer fires while the widget is still parentless.
    """

    class _ShowFilter(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Show:
                watched.removeEventFilter(self)
                self.deleteLater()
                fn()
            return False

    widget.installEventFilter(_ShowFilter(widget))


class WorkspaceManager(QMainWindow):
    """
    A self-contained workspace widget that composes a DockManager with:
      - a code editor panel (center)
      - an OpenGL image viewer panel (center, per file)
      - a directory browser panel (left)
      - a symbols panel (right, optional)
      - an embedded terminal panel (bottom)
      - a status bar with usage hints

    Layout persistence
    ------------------
    Delegated entirely to :class:`WorkspaceLayoutManager`.  Call
    ``save_layout(path)`` / ``restore_layout(path)`` to persist or rebuild
    the full workspace state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dock_manager: DockManager | None = None
        self._dir_mngr: DirectoryWidget | None = None
        self._terminal_widget: TerminalWidget | None = None
        self._sym_widget: SymbolsWidget | None = None
        self._code_editor: CodeEditorWidget | None = None
        self._layout_manager: WorkspaceLayoutManager | None = None

        # Tracks open file paths so the file browser won't open duplicates.
        self._open_paths: set[Path] = set()

        # Cache of colorized icons keyed by SVG path.
        self._icon_cache: dict[str, QIcon] = {}

        # Debounce timer: symbols refresh 500 ms after the last keystroke.
        self._sym_timer = QTimer(self)
        self._sym_timer.setSingleShot(True)
        self._sym_timer.setInterval(500)
        self._sym_timer.timeout.connect(self._refresh_symbols)

        self._setup_ui()
        self._setup_panels()
        self._setup_status_bar()

    # ── internal helpers ──────────────────────────────────────────────────────

    def _icon(self, svg_path: str) -> QIcon:
        if svg_path not in self._icon_cache:
            self._icon_cache[svg_path] = QIcon(
                colorize_pixmap(
                    QPixmap(svg_path),
                    self.palette().accent().color(),
                )
            )
        return self._icon_cache[svg_path]

    def _warn(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, str(exc))

    # ── setup ─────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self._dir_mngr = DirectoryWidget(start_dir=os.getcwd())
        self._code_editor = CodeEditorWidget(show_symbols=False)
        self._terminal_widget = TerminalWidget()

        if _SYMBOLS_AVAILABLE:
            self._sym_widget = SymbolsWidget()

        self._dock_manager = DockManager(title="Workspace Manager")

        self._layout_manager = WorkspaceLayoutManager(
            dock_manager=self._dock_manager,
            code_editor=self._code_editor,
            open_in_editor=self._open_in_editor,
            on_paths_restored=self._open_paths.update,
        )

        self.setCentralWidget(self._dock_manager)

    def _setup_panels(self):
        dm = self._dock_manager

        dm.register_panel_provider(self._panel_provider)

        # ── Center: Code Editor ───────────────────────────────────────
        dm.add_panel(
            "center", self._code_editor, "Code",
            self._icon("line-icons:file-code.svg"),
            closable=False,
            panel_id=_ID_EDITOR,
        )

        # ── Left: Directory Browser ───────────────────────────────────
        dm.add_panel(
            "left", self._dir_mngr, "Project",
            self._icon("line-icons:folder-5.svg"),
            closable=False,
            panel_id=_ID_FILES,
        )
        self._dir_mngr.file_opened.connect(self._on_file_opened)

        # ── Right: Symbols (optional) ─────────────────────────────────
        if self._sym_widget is not None:
            dm.add_panel(
                "right", self._sym_widget, "Symbols",
                self._icon("other-icons:list-check-3.svg"),
                closable=False,
                panel_id=_ID_SYMBOLS,
            )
            self._sym_widget.symbol_activated.connect(self._on_symbol_activated)
            self._code_editor.tabs.currentChanged.connect(
                self._on_editor_tab_changed
            )

        # ── Bottom: Terminal ──────────────────────────────────────────
        dm.add_panel(
            "bottom", self._terminal_widget, "Terminal",
            self._icon("line-icons:code-box.svg"),
            closable=False,
            panel_id=_ID_TERMINAL,
        )

    def _setup_status_bar(self):
        sb = QStatusBar()
        sb.showMessage(
            "Drag a tab onto the light-blue region to dock  ·  "
            "Drag outside the center region to float  ·  "
            "Blue border = focused region"
        )
        self._dock_manager.setStatusBar(sb)

    # ── panel provider ────────────────────────────────────────────────────────

    def _panel_provider(self, panel_id: str) -> tuple | None:
        """
        Map a saved *panel_id* back to a live widget tuple.

        Returns ``(widget, title, icon, closable)`` or ``None``.
        """
        # ── Fixed panels ──────────────────────────────────────────────
        if panel_id == _ID_EDITOR:
            return (self._code_editor, "Code",
                    self._icon("line-icons:file-code.svg"), False)
        if panel_id == _ID_FILES:
            return (self._dir_mngr, "Project",
                    self._icon("line-icons:folder-5.svg"), False)
        if panel_id == _ID_SYMBOLS and self._sym_widget is not None:
            return (self._sym_widget, "Symbols",
                    self._icon("other-icons:list-check-3.svg"), False)
        if panel_id == _ID_TERMINAL:
            return (self._terminal_widget, "Terminal",
                    self._icon("line-icons:code-box.svg"), False)

        # ── Dynamic (file-based) panels ───────────────────────────────
        path = self._layout_manager.dynamic_panels.get(panel_id)
        if path is None or not path.exists():
            return None

        result = self._create_widget_for_path(path)
        if result is None:
            return None

        widget, title, icon = result
        widget.setProperty(DOCK_PANEL_ID_PROPERTY, panel_id)
        return (widget, title, icon, True)

    # ── widget factory ────────────────────────────────────────────────────────

    def _create_widget_for_path(self, path: Path) -> tuple | None:
        """
        Instantiate the appropriate viewer widget for *path*.

        Returns ``(widget, title, icon)`` or ``None``.  Shared by
        ``_on_file_opened`` (first open) and ``_panel_provider`` (restore).
        """
        info = build_file_info(path)
        stem = path.stem

        match info.category:
            case FileExtensionCategory.IMAGE:
                try:
                    buf, _ = load_image(path, backend=Backend.PILLOW)
                    data = np.flipud(buf.data)
                    widget = GLImageShow()
                    _defer_until_shown(widget, lambda: widget.set_data(data))
                    return widget, stem, self._icon("line-icons:image.svg")
                except Exception as exc:
                    self._warn("Image Load Error", exc)
                    return None

            case FileExtensionCategory.VIDEO:
                try:
                    widget = VideoPlaybackWidget(video_path=path)
                    _defer_until_shown(widget, widget.start)
                    return widget, stem, self._icon("line-icons:film.svg")
                except Exception as exc:
                    self._warn("Video Load Error", exc)
                    return None

            case FileExtensionCategory.PDF:
                try:
                    widget = PDFViewer()
                    widget._load(str(path))
                    return widget, stem, self._icon("line-icons:file.svg")
                except Exception as exc:
                    self._warn("PDF Load Error", exc)
                    return None

            case FileExtensionCategory.MODEL_3D:
                try:
                    widget = ModelViewerWidget()
                    widget.load_model(str(path))
                    return widget, stem, self._icon("line-icons:box-3-line.svg")
                except Exception as exc:
                    self._warn("Model Load Error", exc)
                    return None

            case _:
                return None

    # ── symbols panel ─────────────────────────────────────────────────────────

    def _refresh_symbols(self) -> None:
        if self._sym_widget is None:
            return
        ed = self._code_editor.tabs.currentWidget()
        if not isinstance(ed, CodeEditor):
            self._sym_widget.clear()
            return
        lang_tag = LANG_TO_SYMBOLS.get(ed.language.name)
        if lang_tag is None:
            self._sym_widget.clear()
            return
        self._sym_widget.load_source(ed.toPlainText(), lang_tag)

    def _on_editor_tab_changed(self, _idx: int) -> None:
        self._sym_timer.stop()
        self._refresh_symbols()

    def _on_symbol_activated(self, line: int, col: int) -> None:
        ed = self._code_editor.tabs.currentWidget()
        if isinstance(ed, CodeEditor) and hasattr(ed, "goto_line_col"):
            ed.goto_line_col(line, col)
        elif isinstance(ed, CodeEditor):
            ed.goto_line(line)

    def _connect_editor_content_signals(self, ed: CodeEditor) -> None:
        ed.document().contentsChanged.connect(self._sym_timer.start)

    # ── file dispatch ─────────────────────────────────────────────────────────

    def _on_file_opened(self, info: FileInfo) -> None:
        if info.path in self._open_paths:
            self._dock_manager.focus_panel(self._code_editor)
            return

        match info.category:
            case FileExtensionCategory.CODE:
                self._open_in_editor(info.path)

            case (
                FileExtensionCategory.IMAGE
                | FileExtensionCategory.VIDEO
                | FileExtensionCategory.PDF
                | FileExtensionCategory.MODEL_3D
            ):
                result = self._create_widget_for_path(info.path)
                if result is None:
                    return
                widget, title, icon = result
                handle = self._dock_manager.add_panel(
                    "center", widget, title, icon,
                )
                # Register with the layout manager so the path is persisted.
                self._layout_manager.dynamic_panels[handle.id] = info.path
                self._open_paths.add(info.path)

            case _:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(info.path)))

    def _open_in_editor(self, path: Path) -> None:
        path_str = str(path)
        tabs = self._code_editor.tabs
        for i in range(tabs.count()):
            ed = tabs.widget(i)
            if getattr(ed, "filepath", None) == path_str:
                tabs.setCurrentIndex(i)
                self._dock_manager.focus_panel(self._code_editor)
                return

        ed = self._code_editor.add_new_tab(path_str)
        self._connect_editor_content_signals(ed)
        self._dock_manager.focus_panel(self._code_editor)
        self._open_paths.add(path)
        self._sym_timer.stop()
        self._refresh_symbols()

    # ── public layout API ─────────────────────────────────────────────────────

    def dock_manager(self) -> DockManager | None:
        """Return the underlying DockManager."""
        return self._dock_manager

    def save_layout(self, path: str | Path) -> None:
        """Save the current dock layout and all open-panel state."""
        if self._layout_manager is not None:
            self._layout_manager.save_layout(path)

    def restore_layout(self, path: str | Path) -> None:
        """Restore a previously saved dock layout and recreate all panels."""
        if self._layout_manager is not None:
            self._layout_manager.restore_layout(path)

    # ── teardown ──────────────────────────────────────────────────────────────

    def cleanup(self):
        self._sym_timer.stop()

        if self._dock_manager is not None:
            self._dir_mngr.file_opened.disconnect(self._on_file_opened)
            if self._sym_widget is not None:
                self._code_editor.tabs.currentChanged.disconnect(
                    self._on_editor_tab_changed
                )
            self._dock_manager.cleanup()
            self._dock_manager = None

        if self._terminal_widget is not None:
            self._terminal_widget.close()
            self._terminal_widget = None

        if self._dir_mngr is not None:
            self._dir_mngr.close()
            self._dir_mngr = None

        self._sym_widget = None
        self._layout_manager = None
        self._open_paths.clear()
        self._icon_cache.clear()

    def closeEvent(self, event):
        event.accept()
        super().closeEvent(event)
        self.cleanup()


# ── stand-alone entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from qtcore.app import Application

    app = Application(argv=sys.argv)
    app.show_splash(min_display_ms=1000)
    app.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QSurfaceFormat.setDefaultFormat(get_surface_format())

    workspace = WorkspaceManager()
    workspace.showMaximized()

    app.finish_splash(main_window=workspace)
    app.aboutToQuit.connect(workspace.close)

    sys.exit(app.exec())