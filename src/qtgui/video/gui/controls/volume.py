"""
volume_widget.py
================
Cross-platform volume control widget for a video player interface.

The widget is purely UI — it emits signals and owns no audio backend,
so it integrates with any playback engine (GStreamer, VLC, FFmpeg, etc.)
by connecting to its signals.

Usage
-----
    from volume_widget import VolumeWidget

    vol = VolumeWidget()
    vol.volume_changed.connect(player.set_volume)   # receives 0.0 – 1.0
    vol.mute_changed.connect(player.set_muted)      # receives bool

    # Keep the widget in sync with external state changes:
    player.volume_reported.connect(vol.set_volume)

Public API
----------
    vol.volume         -> float   0.0 – 1.0
    vol.is_muted       -> bool
    vol.set_volume(v)             set volume programmatically (no signal loop)
    vol.set_muted(m)              set mute programmatically  (no signal loop)
    vol.toggle_mute()             flip mute state

    signal volume_changed(float)  emitted when the user moves the slider
    signal mute_changed(bool)     emitted when mute is toggled

Keyboard shortcuts (widget must have focus):
    ↑ / ↓       +/- 5 %
    M           toggle mute
    0           set volume to 0
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# SVG-free icon painter  (no external assets required → truly cross-platform)
# ---------------------------------------------------------------------------

class _VolumeIcon(QWidget):
    """
    Scalable speaker icon drawn entirely with QPainter.

    Reacts to volume level (0 / low / mid / high) and muted state by changing
    the number of arc "waves" rendered.  No image files required.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._volume: float = 1.0
        self._muted: bool = False
        self.setFixedSize(22, 22)

    def set_state(self, volume: float, muted: bool) -> None:
        self._volume = volume
        self._muted = muted
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        color = QColor("#606068") if self._muted else QColor("#d4d4d8")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)

        # ── Speaker body (trapezoid) ───────────────────────────────────────
        body = QPainterPath()
        bx = w * 0.12
        body.moveTo(bx + w * 0.16, cy - h * 0.16)
        body.lineTo(bx + w * 0.30, cy - h * 0.28)
        body.lineTo(bx + w * 0.30, cy + h * 0.28)
        body.lineTo(bx + w * 0.16, cy + h * 0.16)
        body.closeSubpath()
        p.drawPath(body)

        # Cone
        cone = QPainterPath()
        cone.moveTo(bx + w * 0.16, cy - h * 0.16)
        cone.lineTo(bx,            cy - h * 0.16)
        cone.lineTo(bx,            cy + h * 0.16)
        cone.lineTo(bx + w * 0.16, cy + h * 0.16)
        cone.closeSubpath()
        p.drawPath(cone)

        if self._muted:
            # ── X mark ────────────────────────────────────────────────────
            pen = QPen(QColor("#c85050"), 1.6, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            mx = bx + w * 0.38
            p.drawLine(int(mx),        int(cy - h * 0.20),
                       int(mx + w * 0.26), int(cy + h * 0.20))
            p.drawLine(int(mx + w * 0.26), int(cy - h * 0.20),
                       int(mx),        int(cy + h * 0.20))
        else:
            # ── Sound waves ───────────────────────────────────────────────
            waves = 0
            if self._volume > 0.0:   waves = 1
            if self._volume > 0.35:  waves = 2
            if self._volume > 0.65:  waves = 3

            pen = QPen(color, 1.4, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)

            from PyQt6.QtCore import QRectF
            origin_x = bx + w * 0.34
            for i in range(waves):
                r = w * (0.14 + i * 0.12)
                rect = QRectF(origin_x, cy - r, r, r * 2)
                p.drawArc(rect, -60 * 16, 120 * 16)

        p.end()


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

_STYLESHEET = """
VolumeWidget {
    background: transparent;
}

/* Slider groove */
QSlider::groove:horizontal {
    height: 2px;
    background: #2a2a33;
    border-radius: 1px;
}

/* Filled portion */
QSlider::sub-page:horizontal {
    background: #e8a020;
    border-radius: 1px;
}

/* Muted filled portion */
QSlider[muted="true"]::sub-page:horizontal {
    background: #606068;
}

/* Handle */
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
QSlider[muted="true"]::handle:horizontal {
    background: #606068;
}

/* Percentage label */
QLabel#volLabel {
    color: #606068;
    font-family: "Courier New", monospace;
    font-size: 10px;
    min-width: 28px;
    max-width: 28px;
    qproperty-alignment: AlignRight;
}

/* Mute button */
QToolButton#muteBtn {
    background: transparent;
    border: none;
    padding: 0;
}
QToolButton#muteBtn:hover  { background: rgba(255,255,255,0.04); border-radius: 3px; }
QToolButton#muteBtn:pressed{ background: rgba(255,255,255,0.08); }
"""


# ---------------------------------------------------------------------------
# VolumeWidget
# ---------------------------------------------------------------------------

class VolumeWidget(QWidget):
    """
    Compact horizontal volume control: [icon] [━━●━━━━━] [100%]

    Signals
    -------
    volume_changed(float):
        Emitted when the user adjusts the slider.  Value is 0.0 – 1.0.
        Connect this to your player's set_volume() method.

    mute_changed(bool):
        Emitted when mute is toggled.  ``True`` means muted.
        Connect this to your player's set_muted() method.
    """

    volume_changed = pyqtSignal(float)
    mute_changed   = pyqtSignal(bool)

    # Slider uses integer ticks for precision; 1 tick == 0.01 volume.
    _TICKS = 100

    def __init__(
        self,
        initial_volume: float = 1.0,
        initial_muted: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(_STYLESHEET)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._volume: float = float(max(0.0, min(1.0, initial_volume)))
        self._muted:  bool  = initial_muted
        self._pre_mute_volume: float = self._volume   # restore on unmute

        self._build_ui()
        self._sync_ui(emit=False)

    # ── construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Speaker icon / mute button
        self._icon = _VolumeIcon()
        self._mute_btn = QToolButton()
        self._mute_btn.setObjectName("muteBtn")
        self._mute_btn.setFixedSize(22, 22)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.setToolTip("Toggle mute  [M]")

        # Overlay icon onto the button using a nested layout
        btn_layout = QHBoxLayout(self._mute_btn)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(self._icon)

        layout.addWidget(self._mute_btn)

        # Slider
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, self._TICKS)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(5)
        self._slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self._slider.setToolTip("Volume")
        layout.addWidget(self._slider)

        # Percentage label
        self._label = QLabel()
        self._label.setObjectName("volLabel")
        layout.addWidget(self._label)

        # Connections
        self._slider.valueChanged.connect(self._on_slider_moved)
        self._mute_btn.clicked.connect(self.toggle_mute)

    # ── internal sync ─────────────────────────────────────────────────────

    def _sync_ui(self, emit: bool = True) -> None:
        """Push current ``_volume`` / ``_muted`` into every control."""
        # Slider — block its signal to avoid a re-entrant emit
        self._slider.blockSignals(True)
        self._slider.setValue(int(self._volume * self._TICKS))
        self._slider.blockSignals(False)

        # Dynamic property drives the muted stylesheet variant
        self._slider.setProperty("muted", self._muted)
        self._slider.style().unpolish(self._slider)
        self._slider.style().polish(self._slider)

        # Label
        pct = int(self._volume * 100)
        self._label.setText(f"{pct}%")
        self._label.setStyleSheet(
            "color: #606068;" if self._muted else "color: #a0a0b0;"
        )

        # Icon
        self._icon.set_state(self._volume, self._muted)

        if emit:
            self.volume_changed.emit(self._volume)

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_slider_moved(self, tick: int) -> None:
        self._volume = tick / self._TICKS
        # Dragging slider implicitly unmutes
        if self._muted and tick > 0:
            self._muted = False
            self.mute_changed.emit(False)
        self._sync_ui(emit=True)

    # ── public API ────────────────────────────────────────────────────────

    @property
    def volume(self) -> float:
        """Current volume as a float in [0.0, 1.0]."""
        return self._volume

    @property
    def is_muted(self) -> bool:
        """``True`` when muted."""
        return self._muted

    def set_volume(self, value: float, *, emit: bool = False) -> None:
        """
        Set volume programmatically.

        Args:
            value:  Clamped to [0.0, 1.0].
            emit:   Set ``True`` to fire ``volume_changed``; default is
                    ``False`` so external state pushes don't feed back into
                    the player.
        """
        self._volume = max(0.0, min(1.0, float(value)))
        self._sync_ui(emit=emit)

    def set_muted(self, muted: bool, *, emit: bool = False) -> None:
        """
        Set mute state programmatically.

        Args:
            muted:  ``True`` to mute.
            emit:   Set ``True`` to fire ``mute_changed``.
        """
        if muted and not self._muted:
            self._pre_mute_volume = self._volume
        elif not muted and self._muted:
            # Restore pre-mute level if volume was zeroed while muted
            if self._volume == 0.0:
                self._volume = self._pre_mute_volume or 1.0
        self._muted = muted
        self._sync_ui(emit=False)
        if emit:
            self.mute_changed.emit(self._muted)

    def toggle_mute(self) -> None:
        """Flip mute state and emit ``mute_changed``."""
        self.set_muted(not self._muted, emit=True)

    # ── keyboard ──────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Up:
            self.set_volume(self._volume + 0.05, emit=True)
        elif key == Qt.Key.Key_Down:
            self.set_volume(self._volume - 0.05, emit=True)
        elif key == Qt.Key.Key_M:
            self.toggle_mute()
        elif key == Qt.Key.Key_0:
            self.set_volume(0.0, emit=True)
        else:
            super().keyPressEvent(event)

    # ── scroll wheel ──────────────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Scroll wheel nudges volume ±5 %."""
        delta = event.angleDelta().y()
        step = 0.05 if delta > 0 else -0.05
        self.set_volume(self._volume + step, emit=True)
        event.accept()


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    demo = QWidget()
    demo.setWindowTitle("Volume Widget Demo")
    demo.setStyleSheet("background: #0e0e11;")
    demo.setFixedSize(340, 80)

    layout = QVBoxLayout(demo)
    layout.setContentsMargins(20, 20, 20, 20)

    vol = VolumeWidget(initial_volume=0.75)
    vol.volume_changed.connect(lambda v: print(f"volume → {v:.2f}"))
    vol.mute_changed.connect(lambda m: print(f"muted  → {m}"))
    layout.addWidget(vol)

    demo.show()
    sys.exit(app.exec())