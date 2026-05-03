"""
video_controls_widget.py
========================
Transparent overlay control bar for the video player.

Public contract (unchanged from original):
    Signals
        play_pause_clicked(bool)   True = play, False = pause
        stop_clicked()
        forward_clicked()
        backward_clicked()
        reverse_clicked(bool)      True = reverse enabled
        seek_requested(int)        position in milliseconds
        volume_changed(float)      volume 0.0 – 1.0

    Slots / public methods
        set_duration(ms: int)
        set_position(ms: int)
        set_playing_state(playing: bool)
        update_time_display(current_ms, total_ms)
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap, QPalette
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtgui.video.gui.controls.volume import VolumeWidget
from qtgui.pixmap import colorize_pixmap


# ---------------------------------------------------------------------------
# Design tokens  (keep in sync with the rest of the video UI)
# ---------------------------------------------------------------------------

_ACCENT       = "#e8a020"
_ACCENT_HOVER = "#f0b840"
_BTN_BG       = "rgba(255, 255, 255, 0.12)"
_BTN_HOVER    = "rgba(255, 255, 255, 0.22)"
_BTN_PRESSED  = "rgba(255, 255, 255, 0.32)"
_BTN_CHECKED  = _ACCENT
_WHITE        = "white"
_ICON_SIZE    = QSize(256, 256)
_ICON_COLOR   = QColor(_WHITE)

_STYLESHEET = f"""
/* ── Transport buttons ───────────────────────────────────────────── */
QToolButton {{
    background: {_BTN_BG};
    color: {_WHITE};
    border: none;
    border-radius: 5px;
}}
QToolButton:hover   {{ background: {_BTN_HOVER}; }}
QToolButton:pressed {{ background: {_BTN_PRESSED}; }}
QToolButton:checked {{ background: {_BTN_CHECKED}; border-radius: 5px; }}

/* ── Position / seek slider ──────────────────────────────────────── */
QSlider#positionSlider::groove:horizontal {{
    background: rgba(255, 255, 255, 0.25);
    height: 4px;
    border-radius: 2px;
}}
QSlider#positionSlider::handle:horizontal {{
    background: {_WHITE};
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}
QSlider#positionSlider::sub-page:horizontal {{
    background: {_ACCENT};
    border-radius: 2px;
}}

/* ── Time label ──────────────────────────────────────────────────── */
QLabel#timeLabel {{
    color: rgba(255, 255, 255, 0.85);
    font-family: "Courier New", monospace;
    font-size: 11px;
}}

QLabel#totalTimeLabel {{
    color: rgba(255, 255, 255, 0.85);
    font-family: "Courier New", monospace;
    font-size: 11px;
}}
"""


def _icon(icon_path: str) -> QIcon:
    """Return a white icon of the standard transport size."""
    return QIcon(colorize_pixmap(QPixmap(icon_path), QColor("white")))


def _tool_button(
    icon_path: str,
    size: int,
    *,
    checkable: bool = False,
    tooltip: str = "",
) -> QToolButton:
    """
    Construct a styled QToolButton with a vector icon.

    Args:
        icon_path:  Icon to display.
        size:       Width and height in pixels (square).
        checkable:  Whether the button is a toggle.
        tooltip:    Optional tooltip string.
    """
    btn = QToolButton()
    btn.setIcon(_icon(icon_path))
    btn.setFixedSize(size, size)
    btn.setCheckable(checkable)
    btn.setIconSize(QSize(size - 10, size - 10))
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def _ms_to_time_str(ms: int) -> str:
    """
    Format *ms* milliseconds as ``HH:MM:SS`` (hours omitted when zero).

    Examples:
        3_661_000 → "1:01:01"
        90_000    → "01:30"
    """
    total_sec = max(0, ms // 1000)
    h, rem    = divmod(total_sec, 3600)
    m, s      = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# VideoControlsWidget
# ---------------------------------------------------------------------------

class VideoControlsWidget(QWidget):
    """
    Transparent overlay containing video playback controls.

    Layout (bottom-up):
        [volume ────────── ◀  ▶▶  ▶ ──────────── ⚙]   ← transport row
        [MM:SS  ━━━━●━━━━━━━━━━━━━━━━━━━━━━  MM:SS]   ← scrub row

    The widget owns no playback state beyond ``_is_playing`` / ``_is_reverse``
    (needed to toggle button icons).  Everything else is driven externally via
    the public slots.

    Signals
    -------
    play_pause_clicked(bool)    True = play, False = pause.
    stop_clicked()
    forward_clicked()
    backward_clicked()
    reverse_clicked(bool)       True = reverse mode enabled.
    seek_requested(int)         Requested position in milliseconds.
    volume_changed(float)       Volume level 0.0 – 1.0.
    """

    play_pause_clicked = pyqtSignal(bool)
    stop_clicked       = pyqtSignal()
    forward_clicked    = pyqtSignal()
    backward_clicked   = pyqtSignal()
    reverse_clicked    = pyqtSignal(bool)
    seek_requested     = pyqtSignal(int)
    volume_changed     = pyqtSignal(float)
    subtitle_requested = pyqtSignal(bool)
    settings_requested = pyqtSignal(bool)

    # Slider uses 0–1000 internally so seeks are sub-second precise.
    _SLIDER_RESOLUTION = 1000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Playback state — only what we need to update button icons.
        self._is_playing: bool = False
        self._is_reverse: bool = False
        self._duration_ms: int = 0
        self._last_volume: float = 1.0

        self.setMouseTracking(True)

        self._setup_background()
        self.setStyleSheet(_STYLESHEET)
        self._build_ui()
        self._wire_ui()

    # ------------------------------------------------------------------
    # Background
    # ------------------------------------------------------------------

    def _setup_background(self) -> None:
        """Semi-transparent dark background — works on all platforms."""
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 120))
        self.setPalette(palette)

    # ------------------------------------------------------------------
    # UI construction  (one method per logical section)
    # ------------------------------------------------------------------

    def _wire_ui(self):
        self.volume_widget.volume_changed.connect(self._on_volume_changed)
        self.volume_widget.mute_changed.connect(self._on_mute_changed)

        self.play_pause_btn.clicked.connect(self._on_play_pause_clicked)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(6)
        root.addLayout(self._build_transport_row())
        root.addLayout(self._build_scrub_row())

    def _build_transport_row(self) -> QHBoxLayout:
        """Volume ── [backward | play/pause | forward] ── settings."""
        layout = QHBoxLayout()
        layout.setSpacing(5)

        # ── Volume (left-anchored) ─────────────────────────────────────────
        self.volume_widget = VolumeWidget(initial_volume=1.0, parent=self)
        self.volume_widget.setFixedWidth(160)

        layout.addWidget(self.volume_widget)

        layout.addStretch()

        # ── Transport buttons (centre) ─────────────────────────────────────
        self.backward_btn = _tool_button(
            "line-icons:rewind-line.svg", 36, tooltip="Step backward"
        )
        self.backward_btn.clicked.connect(self.backward_clicked)

        self.play_pause_btn = _tool_button(
            "line-icons:play-line.svg", 46, tooltip="Play / Pause  [Space]"
        )

        self.forward_btn = _tool_button(
            "line-icons:speed-line.svg", 36, tooltip="Step forward"
        )
        self.forward_btn.clicked.connect(self.forward_clicked)

        layout.addWidget(self.backward_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.play_pause_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.forward_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addSpacing(10)
        layout.addStretch()

        self.subtitle_btn = QToolButton()
        self.subtitle_btn.setCheckable(True)
        self.subtitle_btn.setIcon(
            QIcon(colorize_pixmap(QPixmap("line-icons:chat-settings.svg"),
                                  _ICON_COLOR))
        )
        self.subtitle_btn.setFixedSize(36, 36)
        self.subtitle_btn.setToolTip("Video subtitle")
        self.subtitle_btn.toggled.connect(self.subtitle_requested)
        layout.addWidget(self.subtitle_btn)


        # ── Settings toggle (right-anchored) ──────────────────────────────
        self.settings_btn = QToolButton()
        self.settings_btn.setIcon(
            QIcon(colorize_pixmap(QPixmap("line-icons:film.svg"), _ICON_COLOR))
        )
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setCheckable(True)
        self.settings_btn.setToolTip("Video settings")
        self.settings_btn.toggled.connect(self.settings_requested)
        layout.addWidget(self.settings_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        return layout

    def _build_scrub_row(self) -> QHBoxLayout:
        """Time label ── seek slider."""
        layout = QHBoxLayout()
        layout.setSpacing(10)

        self.current_time_label = QLabel("00:00")
        self.current_time_label.setObjectName("timeLabel")
        # self.current_time_label.setFixedWidth(100)
        layout.addWidget(self.current_time_label)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setObjectName("positionSlider")
        self.position_slider.setRange(0, self._SLIDER_RESOLUTION)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self.position_slider, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.total_time_label = QLabel("00:00")
        self.total_time_label.setObjectName("totalTimeLabel")
        # self.total_time_label.setFixedWidth(100)
        layout.addWidget(self.total_time_label)

        return layout

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _on_play_pause_clicked(self) -> None:
        self._is_playing = not self._is_playing
        self._refresh_play_icon()
        self.play_pause_clicked.emit(self._is_playing)

    def _on_volume_changed(self, volume: float) -> None:
        if volume > 0.0:
            self._last_volume = volume
        self.volume_changed.emit(volume)

    def _on_mute_changed(self, muted: bool) -> None:
        """Mute state from the volume widget — emit zero volume when muted."""
        if muted:
            self.volume_changed.emit(0.0)
        else:
            self.volume_changed.emit(self._last_volume)

    def _on_slider_moved(self, position: int) -> None:
        """Convert slider ticks to milliseconds and emit."""
        if self._duration_ms > 0:
            ms = int((position / self._SLIDER_RESOLUTION) * self._duration_ms)
            self.seek_requested.emit(ms)

    # ------------------------------------------------------------------
    # Icon helpers
    # ------------------------------------------------------------------

    def _refresh_play_icon(self) -> None:
        icon_path = "line-icons:pause-line.svg" if self._is_playing else (
            "line-icons:play-line.svg")
        self.play_pause_btn.setIcon(_icon(icon_path))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_duration(self, duration_ms: int) -> None:
        """Inform the widget of the total video duration in milliseconds."""
        self._duration_ms = max(0, duration_ms)
        self.update_time_display(0, self._duration_ms)

    def set_position(self, position_ms: int) -> None:
        """
        Update the scrub slider and time label to *position_ms*.

        Signals from the slider are blocked during the update so the seek
        feedback loop cannot fire.
        """
        if self._duration_ms <= 0:
            return
        self.update_time_display(position_ms, self._duration_ms)
        self.position_slider.blockSignals(True)
        tick = int((position_ms / self._duration_ms) * self._SLIDER_RESOLUTION)
        self.position_slider.setValue(tick)
        self.position_slider.blockSignals(False)

    def set_playing_state(self, playing: bool) -> None:
        """Synchronize the play/pause button with an external state change."""
        self._is_playing = playing
        self._refresh_play_icon()

    def update_time_display(self, current_ms: int, total_ms: int) -> None:
        """Render ``current / total`` in the time label."""
        self.current_time_label.setText(
            f"{_ms_to_time_str(current_ms)}"
        )

        self.total_time_label.setText(
            f"{_ms_to_time_str(total_ms)}"
        )