"""
label.py
====================
Popup dialog for subtitle file selection, position, and style settings.

Public contract:
    Signals
        subtitle_file_selected(str)     full path, or "" when cleared
        subtitle_position_changed(SubtitlePosition)
        subtitle_offset_changed(int)
        subtitle_style_changed(SubtitleStyle)
        dialog_closed()                 emitted when the dialog is hidden

    Methods
        set_subtitle(path: str)
        clear_subtitle()
        current_subtitle() -> str
        get_style()        -> SubtitleStyle
        apply_style(s)
        show_centered()
        hide_panel()
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import unique, IntEnum, auto
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt, pyqtSlot, QPoint
from PyQt6.QtGui import QFontDatabase, QColor, QHideEvent

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QWidget, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QComboBox, QCheckBox, QSlider, QFileDialog,
    QColorDialog, QApplication, QDialog,
)


# ---------------------------------------------------------------------------
# Style dataclass  (single source of truth for defaults)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

STYLESHEET = """
QWidget#subtitleSelector {
    background-color: #0e0e11;
    color: #d4d4d8;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
}

/* ── Section group boxes ──────────────────────────────────────── */
QGroupBox {
    border: none;
    border-top: 1px solid #2a2a33;
    margin-top: 6px;
    padding-top: 14px;
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 2px;
    color: #55555f;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 2px;
}

/* ── Labels ───────────────────────────────────────────────────── */
QLabel {
    color: #606068;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
    padding: 2px 0;
    background: transparent;
}
QLabel[active="true"] { color: #d4d4d8; }

/* ── Action buttons ───────────────────────────────────────────── */
QPushButton {
    background: transparent;
    border: 1px solid #2a2a33;
    border-radius: 3px;
    color: #55555f;
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 3px 10px;
}
QPushButton:hover   { border-color: #e8a020; color: #e8a020; }
QPushButton:pressed { background: #1d1d23; }
QPushButton:disabled { border-color: #1e1e24; color: #2a2a33; }

/* ── Position toggle buttons ──────────────────────────────────── */
QPushButton#posBtn {
    font-size: 10px;
    letter-spacing: 1px;
    padding: 4px 14px;
}
QPushButton#posBtn:checked {
    background: #e8a020;
    border-color: #e8a020;
    color: #0e0e11;
}

/* ── Colour swatch buttons ────────────────────────────────────── */
QPushButton#swatchBtn {
    min-width: 28px;
    max-width: 28px;
    min-height: 18px;
    max-height: 18px;
    border-radius: 3px;
    padding: 0;
    letter-spacing: 0;
    font-size: 0px;
}

/* ── Spin boxes ───────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {
    background: #15151a;
    border: 1px solid #2a2a33;
    border-radius: 3px;
    color: #d4d4d8;
    font-family: "Courier New", monospace;
    font-size: 10px;
    padding: 1px 4px;
    max-width: 56px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }

/* ── Combo box ────────────────────────────────────────────────── */
QComboBox {
    background: #1d1d23;
    border: 1px solid #2a2a33;
    border-radius: 3px;
    color: #d4d4d8;
    font-size: 10px;
    padding: 2px 6px;
}
QComboBox:focus { border-color: #e8a020; }
QComboBox::drop-down { border: none; width: 14px; }
QComboBox QAbstractItemView {
    background: #1d1d23;
    border: 1px solid #2a2a33;
    selection-background-color: #2a2a40;
    outline: none;
}

/* ── Checkboxes (toggle style) ────────────────────────────────── */
QCheckBox { spacing: 6px; color: #8888a0; }
QCheckBox:checked { color: #d4d4d8; }
QCheckBox::indicator {
    width: 28px; height: 14px;
    border-radius: 7px;
    background: #2a2a33;
    border: none;
}
QCheckBox::indicator:checked { background: #e8a020; }

/* ── Slider (opacity) ─────────────────────────────────────────── */
QSlider::groove:horizontal { height: 2px; background: #2a2a33; border-radius: 1px; }
QSlider::sub-page:horizontal { background: #e8a020; border-radius: 1px; }
QSlider::handle:horizontal {
    width: 10px; height: 10px; margin: -4px 0;
    border-radius: 5px; background: #e8a020;
}

/* ── Close button ─────────────────────────────────────────────── */
QPushButton#closeBtn {
    font-weight: normal;
    font-size: 14px;
    letter-spacing: 0;
    padding: 1px 6px;
    border: 1px solid transparent;
}
QPushButton#closeBtn:hover {
    border-color: #e8a020;
    color: #e8a020;
}
"""

@unique
class SubtitlePosition(IntEnum):
    TOP = auto()
    BOTTOM = auto()


@dataclass
class SubtitleStyle:
    """Immutable-friendly snapshot of all subtitle visual properties."""
    font_family:        str   = "Arial"
    font_size:          int   = 40
    bold:               bool  = True
    text_color:         str   = "#ffffff"   # hex
    outline_color:      str   = "#000000"
    outline_width:      int   = 1
    background_opacity: float = 0.0         # 0.0 – 1.0
    antialiasing:       bool  = True
    position:           SubtitlePosition = SubtitlePosition.BOTTOM
    offset:             int   = 20          # pixels from edge


def _group(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    """Return a (group_box, inner_layout) pair."""
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 4, 8, 8)
    layout.setSpacing(4)
    return box, layout


def _row(label_text: str, widget: QWidget, *, label_width: int = 80) -> QHBoxLayout:
    """Return a horizontal row: fixed-width label + stretching widget."""
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    lbl = QLabel(label_text)
    lbl.setFixedWidth(label_width)
    h.addWidget(lbl)
    h.addWidget(widget)
    h.addStretch()
    return h


def _swatch_button(hex_color: str) -> QPushButton:
    """A small square button that displays a colour swatch."""
    btn = QPushButton()
    btn.setObjectName("swatchBtn")
    btn.setStyleSheet(f"QPushButton#swatchBtn {{ background: {hex_color}; }}")
    return btn


class SubtitleSettingsDialog(QDialog):
    """
    Popup dialog with three sections:

    1. **File** — load / clear a subtitle file.
    2. **Position** — TOP / BOTTOM toggle + pixel offset.
    3. **Style** — font, size, bold, text colour, outline colour/width,
                   background opacity, antialiasing.

    Signals fire on every user interaction so the host widget can apply
    changes without polling.
    """

    subtitle_file_selected    = pyqtSignal(str)
    subtitle_position_changed = pyqtSignal(SubtitlePosition)
    subtitle_offset_changed   = pyqtSignal(int)
    subtitle_style_changed    = pyqtSignal(SubtitleStyle)
    dialog_closed             = pyqtSignal()   # <-- new signal

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("subtitleSelector")
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint
        )
        self.setStyleSheet(STYLESHEET)
        self.setMinimumWidth(300)

        self._current_path: str         = ""
        self._style:        SubtitleStyle = SubtitleStyle()
        self._text_hex:     str         = self._style.text_color
        self._outline_hex:  str         = self._style.outline_color

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 8)
        root.setSpacing(2)

        root.addLayout(self._build_header())
        root.addWidget(self._build_file_section())
        root.addWidget(self._build_position_section())
        root.addWidget(self._build_style_section())

    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setContentsMargins(12, 4, 8, 4)
        title = QLabel("SUBTITLES")
        title.setStyleSheet(
            "color: #55555f; font-size: 9px; font-weight: bold; "
            "letter-spacing: 2px; background: #1d1d23; border-bottom: 1px solid #2a2a33;"
        )
        h.addWidget(title)
        h.addStretch()
        reset = QPushButton("RESET")
        reset.clicked.connect(self._on_reset)
        h.addWidget(reset)

        # ── Close (X) button
        close_btn = QPushButton("\u2715")
        close_btn.setObjectName("closeBtn")
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.hide_panel)
        h.addWidget(close_btn)

        return h

    # ── File section ────────────────────────────────────────────────────

    def _build_file_section(self) -> QGroupBox:
        box, layout = _group("FILE")

        self._file_label = QLabel("No subtitles loaded")
        self._file_label.setWordWrap(True)
        layout.addWidget(self._file_label)

        btn_row = QHBoxLayout()
        self._load_btn = QPushButton("LOAD")
        self._load_btn.clicked.connect(self._on_load_clicked)

        self._clear_btn = QPushButton("CLEAR")
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self.clear_subtitle)

        btn_row.addWidget(self._load_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return box

    # ── Position section ────────────────────────────────────────────────

    def _build_position_section(self) -> QGroupBox:
        box, layout = _group("POSITION")

        # TOP / BOTTOM toggle pair
        pos_row = QHBoxLayout()
        self._top_btn = QPushButton("TOP")
        self._top_btn.setObjectName("posBtn")
        self._top_btn.setCheckable(True)

        self._bottom_btn = QPushButton("BOTTOM")
        self._bottom_btn.setObjectName("posBtn")
        self._bottom_btn.setCheckable(True)
        self._bottom_btn.setChecked(True)   # default

        self._top_btn.clicked.connect(lambda: self._on_position_clicked(SubtitlePosition.TOP))
        self._bottom_btn.clicked.connect(lambda: self._on_position_clicked(SubtitlePosition.BOTTOM))

        pos_row.addWidget(self._top_btn)
        pos_row.addWidget(self._bottom_btn)
        pos_row.addStretch()
        layout.addLayout(pos_row)

        # Pixel offset
        self._offset_spin = QSpinBox()
        self._offset_spin.setRange(0, 500)
        self._offset_spin.setSuffix(" px")
        self._offset_spin.setValue(self._style.offset)
        self._offset_spin.valueChanged.connect(self._on_offset_changed)
        layout.addLayout(_row("Offset", self._offset_spin))

        return box

    # ── Style section ───────────────────────────────────────────────────

    def _build_style_section(self) -> QGroupBox:
        box, layout = _group("STYLE")

        # Font family
        self._font_combo = QComboBox()
        families = sorted(set(QFontDatabase.families()))
        self._font_combo.addItems(families)
        idx = self._font_combo.findText(self._style.font_family)
        if idx >= 0:
            self._font_combo.setCurrentIndex(idx)
        self._font_combo.currentTextChanged.connect(self._on_style_changed)
        layout.addLayout(_row("Font", self._font_combo, label_width=70))

        # Font size + bold on the same row
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(8)
        size_lbl = QLabel("Size")
        size_lbl.setFixedWidth(70)
        size_row.addWidget(size_lbl)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(8, 120)
        self._size_spin.setValue(self._style.font_size)
        self._size_spin.valueChanged.connect(self._on_style_changed)
        size_row.addWidget(self._size_spin)

        self._bold_chk = QCheckBox("Bold")
        self._bold_chk.setChecked(self._style.bold)
        self._bold_chk.toggled.connect(self._on_style_changed)
        size_row.addWidget(self._bold_chk)
        size_row.addStretch()
        layout.addLayout(size_row)

        # Text colour swatch
        self._text_swatch = _swatch_button(self._text_hex)
        self._text_swatch.clicked.connect(self._on_pick_text_color)
        layout.addLayout(_row("Text", self._text_swatch, label_width=70))

        # Outline colour + width on the same row
        outline_row = QHBoxLayout()
        outline_row.setContentsMargins(0, 0, 0, 0)
        outline_row.setSpacing(8)
        outline_lbl = QLabel("Outline")
        outline_lbl.setFixedWidth(70)
        outline_row.addWidget(outline_lbl)

        self._outline_swatch = _swatch_button(self._outline_hex)
        self._outline_swatch.clicked.connect(self._on_pick_outline_color)
        outline_row.addWidget(self._outline_swatch)

        self._outline_spin = QSpinBox()
        self._outline_spin.setRange(0, 10)
        self._outline_spin.setValue(self._style.outline_width)
        self._outline_spin.setToolTip("Outline width (px)")
        self._outline_spin.valueChanged.connect(self._on_style_changed)
        outline_row.addWidget(self._outline_spin)
        outline_row.addStretch()
        layout.addLayout(outline_row)

        # Background opacity slider
        opacity_row = QHBoxLayout()
        opacity_row.setContentsMargins(0, 0, 0, 0)
        opacity_row.setSpacing(8)
        opacity_lbl = QLabel("BG Opacity")
        opacity_lbl.setFixedWidth(70)
        opacity_row.addWidget(opacity_lbl)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(int(self._style.background_opacity * 100))
        self._opacity_slider.valueChanged.connect(self._on_style_changed)
        opacity_row.addWidget(self._opacity_slider)

        self._opacity_label = QLabel("0%")
        self._opacity_label.setFixedWidth(30)
        opacity_row.addWidget(self._opacity_label)
        layout.addLayout(opacity_row)

        # Antialiasing toggle
        self._aa_chk = QCheckBox("Antialiasing")
        self._aa_chk.setChecked(self._style.antialiasing)
        self._aa_chk.toggled.connect(self._on_style_changed)
        layout.addWidget(self._aa_chk)

        return box

    # ------------------------------------------------------------------
    # Slots — file
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _on_load_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Subtitle File",
            "",
            "Subtitle Files (*.srt *.vtt *.ass *.ssa *.sub *.txt);;All Files (*)",
        )
        if file_path:
            self.set_subtitle(file_path)

    # ------------------------------------------------------------------
    # Slots — position
    # ------------------------------------------------------------------

    def _on_position_clicked(self, position: SubtitlePosition) -> None:
        """Enforce mutual exclusivity and emit."""
        self._top_btn.setChecked(position == SubtitlePosition.TOP)
        self._bottom_btn.setChecked(position == SubtitlePosition.BOTTOM)
        self._style = SubtitleStyle(**{**self._style.__dict__, "position": position})
        self.subtitle_position_changed.emit(position)

    def _on_offset_changed(self, value: int) -> None:
        self._style = SubtitleStyle(**{**self._style.__dict__, "offset": value})
        self.subtitle_offset_changed.emit(value)

    # ------------------------------------------------------------------
    # Slots — style
    # ------------------------------------------------------------------

    def _on_style_changed(self, *_) -> None:
        """Rebuild the style snapshot and emit."""
        pct = self._opacity_slider.value()
        self._opacity_label.setText(f"{pct}%")
        self._style = self._read_style()
        self.subtitle_style_changed.emit(self._style)

    def _on_pick_text_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._text_hex), self, "Text Colour"
        )
        if color.isValid():
            self._text_hex = color.name()
            self._text_swatch.setStyleSheet(
                f"QPushButton#swatchBtn {{ background: {self._text_hex}; }}"
            )
            self._on_style_changed()

    def _on_pick_outline_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._outline_hex), self, "Outline Colour"
        )
        if color.isValid():
            self._outline_hex = color.name()
            self._outline_swatch.setStyleSheet(
                f"QPushButton#swatchBtn {{ background: {self._outline_hex}; }}"
            )
            self._on_style_changed()

    def _on_reset(self) -> None:
        self.apply_style(SubtitleStyle())

    # ------------------------------------------------------------------
    # Style read / apply
    # ------------------------------------------------------------------

    def _read_style(self) -> SubtitleStyle:
        """Collect current control values into a SubtitleStyle."""
        return SubtitleStyle(
            font_family=self._font_combo.currentText(),
            font_size=self._size_spin.value(),
            bold=self._bold_chk.isChecked(),
            text_color=self._text_hex,
            outline_color=self._outline_hex,
            outline_width=self._outline_spin.value(),
            background_opacity=self._opacity_slider.value() / 100.0,
            antialiasing=self._aa_chk.isChecked(),
            position=(
                SubtitlePosition.TOP
                if self._top_btn.isChecked()
                else SubtitlePosition.BOTTOM
            ),
            offset=self._offset_spin.value(),
        )

    def get_style(self) -> SubtitleStyle:
        """Return the current :class:`SubtitleStyle` snapshot."""
        return self._style

    def apply_style(self, style: SubtitleStyle) -> None:
        """Push a :class:`SubtitleStyle` snapshot into all controls."""
        self._style      = style
        self._text_hex   = style.text_color
        self._outline_hex = style.outline_color

        # Block all signals while bulk-setting to emit exactly once at the end.
        for w in (
            self._font_combo, self._size_spin, self._bold_chk,
            self._outline_spin, self._opacity_slider, self._aa_chk,
            self._offset_spin,
        ):
            w.blockSignals(True)

        idx = self._font_combo.findText(style.font_family)
        if idx >= 0:
            self._font_combo.setCurrentIndex(idx)
        self._size_spin.setValue(style.font_size)
        self._bold_chk.setChecked(style.bold)
        self._outline_spin.setValue(style.outline_width)
        self._opacity_slider.setValue(int(style.background_opacity * 100))
        self._opacity_label.setText(f"{int(style.background_opacity * 100)}%")
        self._aa_chk.setChecked(style.antialiasing)
        self._offset_spin.setValue(style.offset)

        self._text_swatch.setStyleSheet(
            f"QPushButton#swatchBtn {{ background: {self._text_hex}; }}"
        )
        self._outline_swatch.setStyleSheet(
            f"QPushButton#swatchBtn {{ background: {self._outline_hex}; }}"
        )

        is_top = style.position == SubtitlePosition.TOP
        self._top_btn.setChecked(is_top)
        self._bottom_btn.setChecked(not is_top)

        for w in (
            self._font_combo, self._size_spin, self._bold_chk,
            self._outline_spin, self._opacity_slider, self._aa_chk,
            self._offset_spin,
        ):
            w.blockSignals(False)

        self.subtitle_style_changed.emit(self._style)

    # ------------------------------------------------------------------
    # Public file API
    # ------------------------------------------------------------------

    def set_subtitle(self, file_path: str) -> None:
        """Load *file_path* as the active subtitle; pass "" to clear."""
        if not file_path:
            self.clear_subtitle()
            return
        self._current_path = file_path
        stem = Path(file_path).stem
        self._file_label.setText(f"Subtitles: {stem}")
        self._file_label.setProperty("active", "true")
        self._file_label.style().unpolish(self._file_label)
        self._file_label.style().polish(self._file_label)
        self._clear_btn.setEnabled(True)
        self.subtitle_file_selected.emit(file_path)

    def clear_subtitle(self) -> None:
        """Clear the active subtitle file."""
        self._current_path = ""
        self._file_label.setText("No subtitles loaded")
        self._file_label.setProperty("active", "false")
        self._file_label.style().unpolish(self._file_label)
        self._file_label.style().polish(self._file_label)
        self._clear_btn.setEnabled(False)
        self.subtitle_file_selected.emit("")

    def current_subtitle(self) -> str:
        """Return the full path of the active subtitle file, or ""."""
        return self._current_path

    # ------------------------------------------------------------------
    # Show centered on screen
    # ------------------------------------------------------------------

    # ── Show centered on parent (not the screen) ──────────────────────────

    def show_centered(self) -> None:
        """
        Show the dialog centered on its parent widget.

        If the dialog has no parent, it falls back to centering on the primary screen.
        """
        self.adjustSize()
        parent = self.parent()
        if parent is not None:
            # Center on parent's global rectangle
            parent_rect = parent.rect()
            parent_center_global = parent.mapToGlobal(parent_rect.center())
            x = parent_center_global.x() - self.width() // 2
            y = parent_center_global.y() - self.height() // 2
        else:
            # Fallback: center on primary screen available geometry
            screen = QApplication.primaryScreen()
            if screen is not None:
                screen_geom = screen.availableGeometry()
            else:
                screen_geom = QApplication.primaryScreen().availableGeometry()
            x = screen_geom.x() + (screen_geom.width() - self.width()) // 2
            y = screen_geom.y() + (screen_geom.height() - self.height()) // 2

        self.move(x, y)
        self.show()
        self.activateWindow()
        self.raise_()

    def hide_panel(self) -> None:
        """Hide the dialog."""
        self.hide()

    # ------------------------------------------------------------------
    # Override hideEvent to emit dialog_closed
    # ------------------------------------------------------------------
    def hideEvent(self, event: QHideEvent) -> None:
        """Emit dialog_closed when the dialog is hidden."""
        self.dialog_closed.emit()
        super().hideEvent(event)