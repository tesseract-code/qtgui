"""
video_settings_dialog.py
========================
PyQt6 dialog for video playback parameters.

Usage (standalone):
    python video_settings_dialog.py

Usage (popup):
    from video_settings_dialog import VideoSettingsDialog

    dialog = VideoSettingsDialog(settings=app_settings)
    dialog.settings_changed.connect(my_callback)   # dict of all values
    dialog.dialog_closed.connect(on_closed)
    dialog.show_centered()

Public API:
    dialog.get_settings() -> VideoSettings   (dataclass snapshot)
    dialog.apply_settings(s: VideoSettings)  (set all controls)
    dialog.reset()                           (restore defaults)
    signal: settings_changed(dict)           (emitted on any change)
    signal: dialog_closed()                  (emitted when hidden)
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QHideEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,                 # <-- changed to QDialog
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from image.settings.base import ImageSettings

# ---------------------------------------------------------------------------
# Settings dataclass  (single source of truth for defaults and field order)
# ---------------------------------------------------------------------------

COLORMAPS = [
    "gray", "viridis", "plasma", "inferno", "magma", "cividis",
    "hot", "cool", "bone", "copper", "jet", "turbo",
    "rainbow", "spring", "summer", "autumn", "winter",
]


@dataclass
class VideoSettings:
    brightness:      float = 0.0
    contrast:        float = 1.0
    gamma:           float = 1.0
    gain:            float = 1.0
    offset:          float = 0.0
    color_balance_r: float = 1.0
    color_balance_g: float = 1.0
    color_balance_b: float = 1.0
    invert:          bool  = False
    interpolation:   bool  = True
    colormap_enabled: bool  = False
    colormap_name:   str   = "gray"
    colormap_reverse: bool  = False


# ---------------------------------------------------------------------------
# Slider config: (label, attr, min, max, step, accent_color_hex)
# ---------------------------------------------------------------------------

_IMAGE_SLIDERS = [
    ("Brightness", "brightness",      -1.0, 1.0, 0.01, "#e8a020"),
    ("Contrast",   "contrast",         0.0, 2.0, 0.01, "#e8a020"),
    ("Gamma",      "gamma",            0.1, 3.0, 0.01, "#e8a020"),
    ("Gain",       "gain",             0.0, 2.0, 0.01, "#e8a020"),
    ("Offset",     "offset",          -1.0, 1.0, 0.01, "#e8a020"),
]

_COLOR_SLIDERS = [
    ("Red",   "color_balance_r", 0.0, 2.0, 0.01, "#c85050"),
    ("Green", "color_balance_g", 0.0, 2.0, 0.01, "#50b864"),
    ("Blue",  "color_balance_b", 0.0, 2.0, 0.01, "#4a82cc"),
]

# ---------------------------------------------------------------------------
# Stylesheet (unchanged)
# ---------------------------------------------------------------------------

STYLESHEET = """
QWidget {
    background-color: #0e0e11;
    color: #d4d4d8;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
}

/* ── Group boxes ─────────────────────────────────────────────── */
QGroupBox {
    border: none;
    border-top: 1px solid #2a2a33;
    margin-top: 6px;
    padding-top: 14px;
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #55555f;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 2px;
}

/* ── Sliders ─────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 2px;
    background: #2a2a33;
    border-radius: 1px;
}
QSlider::handle:horizontal {
    width: 10px;
    height: 10px;
    margin: -4px 0;
    border-radius: 5px;
    background: #e8a020;
}
QSlider::handle:horizontal:hover {
    background: #f0b840;
}

/* ── Spinbox ──────────────────────────────────────────────────── */
QDoubleSpinBox {
    background: #15151a;
    border: 1px solid #2a2a33;
    border-radius: 3px;
    padding: 1px 4px;
    font-family: "Courier New", monospace;
    font-size: 10px;
    color: #d4d4d8;
    min-width: 56px;
    max-width: 56px;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }

/* ── Checkboxes ───────────────────────────────────────────────── */
QCheckBox {
    spacing: 6px;
    color: #8888a0;
}
QCheckBox:checked { color: #d4d4d8; }
QCheckBox::indicator {
    width: 28px;
    height: 14px;
    border-radius: 7px;
    background: #2a2a33;
    border: none;
}
QCheckBox::indicator:checked { background: #e8a020; }

/* ── ComboBox ─────────────────────────────────────────────────── */
QComboBox {
    background: #1d1d23;
    border: 1px solid #2a2a33;
    border-radius: 3px;
    padding: 2px 6px;
    font-family: "Courier New", monospace;
    font-size: 10px;
    color: #d4d4d8;
    min-width: 90px;
}
QComboBox:focus { border-color: #e8a020; }
QComboBox::drop-down { border: none; width: 16px; }
QComboBox::down-arrow { width: 0; height: 0; }
QComboBox QAbstractItemView {
    background: #1d1d23;
    border: 1px solid #2a2a33;
    selection-background-color: #2a2a40;
    selection-color: #d4d4d8;
    outline: none;
}

/* ── Reset button ────────────────────────────────────────────── */
QPushButton#resetBtn {
    background: transparent;
    border: 1px solid #2a2a33;
    border-radius: 3px;
    color: #55555f;
    font-size: 9px;
    letter-spacing: 2px;
    padding: 3px 10px;
}
QPushButton#resetBtn:hover {
    border-color: #e8a020;
    color: #e8a020;
}
QPushButton#resetBtn:pressed { background: #1d1d23; }

/* ── Close button (X) ────────────────────────────────────────── */
QPushButton#closeBtn {
    font-weight: normal;
    font-size: 14px;
    letter-spacing: 0;
    padding: 1px 6px;
    border: 1px solid transparent;
    background: transparent;
    color: #55555f;
}
QPushButton#closeBtn:hover {
    border-color: #e8a020;
    color: #e8a020;
}

/* ── Scroll area ─────────────────────────────────────────────── */
QScrollArea { border: none; }
QScrollBar:vertical {
    background: #0e0e11;
    width: 4px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a2a33;
    border-radius: 2px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# ---------------------------------------------------------------------------
# Custom slider row  (slider + spinbox kept in sync)
# ---------------------------------------------------------------------------

class SliderRow(QWidget):
    """A labelled horizontal slider paired with a spinbox value display."""

    value_changed: pyqtSignal = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        step: float,
        default: float,
        accent: str = "#e8a020",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._min = minimum
        self._max = maximum
        self._step = step
        self._scale = round(1.0 / step)
        self._accent = accent
        self._inhibit = False

        self._build_ui(label, default)
        self._apply_accent(accent)

    def _build_ui(self, label: str, default: float) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setFixedWidth(70)
        lbl.setStyleSheet("color: #606068; font-size: 10px;")
        layout.addWidget(lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(
            int(self._min * self._scale),
            int(self._max * self._scale),
        )
        self._slider.setValue(int(default * self._scale))
        self._slider.setSingleStep(1)
        self._slider.setPageStep(self._scale // 10 or 1)
        layout.addWidget(self._slider)

        self._spin = QDoubleSpinBox()
        self._spin.setRange(self._min, self._max)
        self._spin.setSingleStep(self._step)
        self._spin.setDecimals(2)
        self._spin.setValue(default)
        layout.addWidget(self._spin)

        self._slider.valueChanged.connect(self._on_slider)
        self._spin.valueChanged.connect(self._on_spin)

    def _apply_accent(self, color: str) -> None:
        self._slider.setStyleSheet(
            f"QSlider::handle:horizontal {{ background: {color}; }}"
            f"QSlider::handle:horizontal:hover {{ background: {color}dd; }}"
            f"QSlider::sub-page:horizontal {{ background: {color}66; border-radius: 1px; }}"
        )

    def _on_slider(self, tick: int) -> None:
        if self._inhibit:
            return
        val = tick / self._scale
        self._inhibit = True
        self._spin.setValue(val)
        self._inhibit = False
        self.value_changed.emit(val)

    def _on_spin(self, val: float) -> None:
        if self._inhibit:
            return
        self._inhibit = True
        self._slider.setValue(int(val * self._scale))
        self._inhibit = False
        self.value_changed.emit(val)

    def get_value(self) -> float:
        return self._spin.value()

    def set_value(self, val: float) -> None:
        self._inhibit = True
        self._spin.setValue(val)
        self._slider.setValue(int(val * self._scale))
        self._inhibit = False


# ---------------------------------------------------------------------------
# Section group box helper
# ---------------------------------------------------------------------------

def _make_group(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    group = QGroupBox(title)
    group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    layout = QVBoxLayout(group)
    layout.setContentsMargins(0, 4, 0, 8)
    layout.setSpacing(0)
    return group, layout


def _make_toggle_row(label: str, checked: bool = False) -> tuple[QWidget, QCheckBox]:
    """Return a (widget, checkbox) pair for a toggle row."""
    row = QWidget()
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    h = QHBoxLayout(row)
    h.setContentsMargins(10, 3, 10, 3)
    h.setSpacing(8)
    lbl = QLabel(label)
    lbl.setStyleSheet("color: #606068; font-size: 10px;")
    h.addWidget(lbl)
    h.addStretch()
    chk = QCheckBox()
    chk.setChecked(checked)
    h.addWidget(chk)
    return row, chk


# ---------------------------------------------------------------------------
# Main dialog (was QWidget, now QDialog)
# ---------------------------------------------------------------------------

class VideoSettingsDialog(QDialog):   # <-- changed to QDialog
    """
    Compact settings dialog exposing all VideoSettings fields as interactive
    controls.

    Signals
    -------
    settings_changed(dict):
        Emitted whenever any control changes.  The dict mirrors the fields of
        :class:`VideoSettings` and can be passed directly to ``**kwargs``.
    dialog_closed():
        Emitted when the dialog is hidden (via close button or hide()).
    """

    settings_changed = pyqtSignal(dict)
    dialog_closed = pyqtSignal()              # <-- new signal

    def __init__(self, settings: ImageSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Video Settings")
        self.setMinimumWidth(320)
        self.setMaximumWidth(400)
        self.setMinimumHeight(400)
        self.setStyleSheet(STYLESHEET)

        # Frameless tool dialog (no taskbar entry)
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint
        )

        self._sliders: dict[str, SliderRow] = {}
        self._toggles: dict[str, QCheckBox] = {}
        self._colormap_combo: QComboBox | None = None

        self.settings = settings

        self._build_ui()
        self._connect_signals()

    # ── UI construction (unchanged except header with close button) ──────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 12)
        body_layout.setSpacing(4)

        body_layout.addWidget(self._build_image_section())
        body_layout.addWidget(self._build_color_section())
        body_layout.addWidget(self._build_colormap_section())
        body_layout.addWidget(self._build_options_section())
        body_layout.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet("background: #1d1d23; border-bottom: 1px solid #2a2a33;")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 0, 8, 0)
        title = QLabel("VIDEO SETTINGS")
        title.setStyleSheet(
            "color: #55555f; font-size: 9px; font-weight: bold; letter-spacing: 2px; "
            "background: transparent; border: none;"
        )
        h.addWidget(title)
        h.addStretch()
        btn = QPushButton("RESET")
        btn.setObjectName("resetBtn")
        btn.setFixedHeight(22)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.reset)
        h.addWidget(btn)

        # ── Close button (X) ────────────────────────────────────────────
        close_btn = QPushButton("\u2715")   # ✕
        close_btn.setObjectName("closeBtn")
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.hide_panel)
        h.addWidget(close_btn)

        return header

    def _build_image_section(self) -> QGroupBox:
        group, layout = _make_group("IMAGE")
        for label, attr, lo, hi, step, accent in _IMAGE_SLIDERS:
            default = getattr(VideoSettings(), attr)
            row = SliderRow(label, lo, hi, step, default, accent)
            self._sliders[attr] = row
            layout.addWidget(row)
        return group

    def _build_color_section(self) -> QGroupBox:
        group, layout = _make_group("COLOR BALANCE")
        for label, attr, lo, hi, step, accent in _COLOR_SLIDERS:
            default = getattr(VideoSettings(), attr)
            row = SliderRow(label, lo, hi, step, default, accent)
            self._sliders[attr] = row
            layout.addWidget(row)
        return group

    def _build_colormap_section(self) -> QGroupBox:
        group, layout = _make_group("COLORMAP")
        defaults = VideoSettings()

        # Enabled toggle
        row_w, chk_enabled = _make_toggle_row("Enabled", defaults.colormap_enabled)
        self._toggles["colormap_enabled"] = chk_enabled
        layout.addWidget(row_w)

        # Name selector
        name_row = QWidget()
        h = QHBoxLayout(name_row)
        h.setContentsMargins(10, 3, 10, 3)
        h.setSpacing(8)
        h.addWidget(QLabel("Map").also(lambda l: l.setStyleSheet("color: #606068; font-size: 10px;")))
        h.addStretch()
        combo = QComboBox()
        for name in COLORMAPS:
            combo.addItem(name)
        combo.setCurrentText(defaults.colormap_name)
        self._colormap_combo = combo
        h.addWidget(combo)
        layout.addWidget(name_row)
        self._colormap_name_row = name_row

        # Reverse toggle
        row_rev, chk_rev = _make_toggle_row("Reverse", defaults.colormap_reverse)
        self._toggles["colormap_reverse"] = chk_rev
        layout.addWidget(row_rev)
        self._colormap_reverse_row = row_rev

        self._set_colormap_sub_enabled(defaults.colormap_enabled)
        chk_enabled.toggled.connect(self._set_colormap_sub_enabled)

        return group

    def _build_options_section(self) -> QGroupBox:
        group, layout = _make_group("OPTIONS")
        defaults = VideoSettings()
        for label, attr in [("Invert", "invert"), ("Interpolation", "interpolation")]:
            row_w, chk = _make_toggle_row(label, getattr(defaults, attr))
            self._toggles[attr] = chk
            layout.addWidget(row_w)
        return group

    # ── signal wiring ──────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        for row in self._sliders.values():
            row.value_changed.connect(lambda _: self._emit())
        for chk in self._toggles.values():
            chk.toggled.connect(lambda _: self._emit())
        if self._colormap_combo:
            self._colormap_combo.currentTextChanged.connect(lambda _: self._emit())

    # ── helpers ────────────────────────────────────────────────────────────

    def _set_colormap_sub_enabled(self, enabled: bool) -> None:
        for w in (self._colormap_name_row, self._colormap_reverse_row):
            w.setEnabled(enabled)
            w.setStyleSheet("" if enabled else "opacity: 0.35;")
            for child in w.findChildren(QWidget):
                child.setEnabled(enabled)

    def _emit(self) -> None:
        settings_dict = asdict(self.get_settings())
        self.settings_changed.emit(settings_dict)

        for k, v in settings_dict.items():
            self.settings.update_setting(k, v)

    # ── public API ─────────────────────────────────────────────────────────

    def get_settings(self) -> VideoSettings:
        """Return a :class:`VideoSettings` snapshot of all current values."""
        return VideoSettings(
            brightness=self._sliders["brightness"].get_value(),
            contrast=self._sliders["contrast"].get_value(),
            gamma=self._sliders["gamma"].get_value(),
            gain=self._sliders["gain"].get_value(),
            offset=self._sliders["offset"].get_value(),
            color_balance_r=self._sliders["color_balance_r"].get_value(),
            color_balance_g=self._sliders["color_balance_g"].get_value(),
            color_balance_b=self._sliders["color_balance_b"].get_value(),
            invert=self._toggles["invert"].isChecked(),
            interpolation=self._toggles["interpolation"].isChecked(),
            colormap_enabled=self._toggles["colormap_enabled"].isChecked(),
            colormap_name=self._colormap_combo.currentText(),
            colormap_reverse=self._toggles["colormap_reverse"].isChecked(),
        )

    def apply_settings(self, s: VideoSettings) -> None:
        """Push a :class:`VideoSettings` snapshot into all controls."""
        for attr, row in self._sliders.items():
            row.set_value(getattr(s, attr))
        for attr, chk in self._toggles.items():
            chk.setChecked(getattr(s, attr))
        if self._colormap_combo:
            self._colormap_combo.setCurrentText(s.colormap_name)

    def reset(self) -> None:
        """Restore all controls to their default values."""
        self.apply_settings(VideoSettings())

    # ── Show centered on screen (replaces show_for_button) ─────────────────

    def show_centered(self) -> None:
        """
        Show the dialog centered on the screen.

        Uses the parent widget's screen if available, otherwise the primary screen.
        """
        self.adjustSize()
        if self.parent() is not None:
            parent_center = self.parent().mapToGlobal(
                self.parent().rect().center()
            )
            screen = QApplication.screenAt(parent_center)
        else:
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
        """Hide the dialog (emits dialog_closed)."""
        self.hide()

    # ── Emit signal when hidden ────────────────────────────────────────────

    def hideEvent(self, event: QHideEvent) -> None:
        """Emit dialog_closed when the dialog is hidden."""
        self.dialog_closed.emit()
        super().hideEvent(event)


# Monkey-patch QLabel for one-liner also() chaining
QLabel.also = lambda self, fn: (fn(self), self)[1]