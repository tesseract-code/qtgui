"""
video_player_stack.py
=====================
Composite video player widget with delegated managers.

Managers
    StackVideoManager      – viewer, controls, auto‑hide, settings panel
    StackSubtitleManager   – subtitle label, file selector, subtitle signals

Public API remains identical to the original VideoPlayerStack.
"""

from __future__ import annotations

import logging
import math
from typing import Tuple

import numpy as np
from PyQt6.QtCore import (
    QRect,
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
    QEvent,
    QObject
)
from PyQt6.QtGui import QColor, QFont, QSurfaceFormat
from PyQt6.QtWidgets import QWidget

from image.gl.utils import get_surface_format
from image.gl.view import GLFrameViewer
from image.pipeline.stats import FrameStats, get_frame_stats
from image.settings.base import ImageSettings
from image.settings.pixels import PixelFormat
from qtgui.label import OutlineLabel
from qtgui.video.gui.controls.video import VideoControlsWidget
from qtgui.video.gui.settings.subtitle import SubtitleSettingsDialog, \
    SubtitleStyle, SubtitlePosition
from qtgui.video.gui.settings.video import VideoSettingsDialog

logger = logging.getLogger(__name__)

# How long the controls stay visible after the last mouse movement (ms).
_CONTROLS_HIDE_DELAY_MS = 5_000

# Minimum dimension (px) used when no frame has been received yet.
_FALLBACK_MIN_RESOLUTION: Tuple[int, int] = (100, 100)


# ---------------------------------------------------------------------------
# Aspect-ratio helpers  (pure functions — easy to test in isolation)
# ---------------------------------------------------------------------------

def get_minimum_resolution(shape: Tuple[int, ...]) -> Tuple[int, int]:
    """
    Return the smallest window size that preserves *shape*'s aspect ratio
    while keeping both dimensions ≥ 200 px.

    Args:
        shape:  NumPy array shape (height, width, …).

    Returns:
        ``(width, height)`` in pixels.

    Raises:
        ValueError: if width or height is non-positive.
    """
    h, w = shape[0], shape[1]
    if w <= 0 or h <= 0:
        raise ValueError(f"Shape dimensions must be positive, got w={w} h={h}")

    g = math.gcd(w, h)
    w_ratio = w // g
    h_ratio = h // g
    m = max(math.ceil(200 / w_ratio), math.ceil(200 / h_ratio))
    return (w_ratio * m, h_ratio * m)


def _aspect_rect(video_w: int, video_h: int, container: QRect) -> QRect:
    """
    Return the largest rectangle within *container* that preserves
    the ``video_w × video_h`` aspect ratio (letter- or pillarbox).
    """
    video_aspect = video_w / video_h
    container_aspect = container.width() / container.height()

    if container_aspect > video_aspect:
        # Pillarbox: container is wider than the video.
        new_w = int(container.height() * video_aspect)
        new_h = container.height()
    else:
        # Letterbox: container is taller than the video.
        new_w = container.width()
        new_h = int(container.width() / video_aspect)

    x = container.x() + (container.width() - new_w) // 2
    y = container.y() + (container.height() - new_h) // 2
    return QRect(x, y, new_w, new_h)


# ---------------------------------------------------------------------------
# 1. StackVideoManager  (video display, controls, auto‑hide, settings)
# ---------------------------------------------------------------------------

class VideoOverlayManager(QObject):
    """
    Manages the video display layer:
    viewer + controls + auto‑hide + settings panel.

    Owns the :class:`ImageSettings` object used by both the viewer and
    the settings panel.
    """

    # Playback signals – forwarded from the controls widget.
    play_pause_clicked = pyqtSignal(bool)
    forward_clicked = pyqtSignal()
    backward_clicked = pyqtSignal()
    reverse_clicked = pyqtSignal(bool)
    seek_requested = pyqtSignal(int)
    volume_changed = pyqtSignal(float)
    subtitle_requested = pyqtSignal(bool)

    def __init__(self,
                 image_settings: ImageSettings,
                 parent: QWidget | None
                 ) -> None:
        super().__init__(parent)
        self.settings = image_settings
        self._frame_stats: FrameStats | None = None
        self._min_resolution: Tuple[int, int] = _FALLBACK_MIN_RESOLUTION

        # Viewer
        self.viewer = GLFrameViewer(image_settings, parent=parent)
        self.viewer.setMouseTracking(True)

        # Controls overlay
        self.controls = VideoControlsWidget(parent)
        self.controls.setMouseTracking(True)
        self.controls.hide()

        # Floating settings panel
        self.panel = VideoSettingsDialog(image_settings, parent)
        self.panel.hide()

        # Auto‑hide timer
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_CONTROLS_HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self._hide_controls)

        self._connect_controls_signals()
        self._install_event_filters()

    # ── Internal wiring ──────────────────────────────────────────────

    def _connect_controls_signals(self) -> None:
        c = self.controls
        c.play_pause_clicked.connect(self.play_pause_clicked)
        c.forward_clicked.connect(self.forward_clicked)
        c.backward_clicked.connect(self.backward_clicked)
        c.reverse_clicked.connect(self.reverse_clicked)
        c.seek_requested.connect(self.seek_requested)
        c.volume_changed.connect(self.volume_changed)
        c.subtitle_requested.connect(self.subtitle_requested)
        # Settings toggle is now handled locally
        c.settings_requested.connect(self._on_settings_toggled)

    def _install_event_filters(self) -> None:
        """Monitor mouse activity on the viewer and the controls overlay."""
        self.viewer.installEventFilter(self)
        self.controls.installEventFilter(self)

    # ── Settings panel ───────────────────────────────────────────────

    @pyqtSlot(bool)
    def _on_settings_toggled(self, checked: bool) -> None:
        if checked:
            self.panel.show_centered()
        else:
            self.panel.hide_panel()

    # ── Auto‑hide logic ──────────────────────────────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.viewer:
            if event.type() in (QEvent.Type.Enter,
                                QEvent.Type.MouseMove,
                                QEvent.Type.MouseButtonPress):
                self._show_controls()
            elif event.type() == QEvent.Type.Leave:
                if not self.controls.underMouse():
                    self._start_hide_timer()
        elif obj is self.controls:
            if event.type() == QEvent.Type.Enter:
                self._hide_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                QTimer.singleShot(50, self._start_hide_timer)
        return super().eventFilter(obj, event)

    def _show_controls(self) -> None:
        self.controls.show()
        self._hide_timer.start()

    def _hide_controls(self) -> None:
        self._hide_timer.stop()
        self.controls.hide()

    def _start_hide_timer(self) -> None:
        if not self._hide_timer.isActive():
            self._hide_timer.start()

    # ── Frame handling ────────────────────────────────────────────────

    def set_frame(self, frame: np.ndarray) -> bool:
        """
        Push a new frame to the viewer.
        Returns True if the frame size changed, False otherwise.
        """
        old_stats = self._frame_stats
        self._frame_stats = get_frame_stats(frame)

        if old_stats is None or old_stats.shape != self._frame_stats.shape:
            self._min_resolution = get_minimum_resolution(
                self._frame_stats.shape
            )
            # Always present the frame after size change
            self.viewer.present(frame, self._frame_stats, PixelFormat.BGR)
            return True

        self.viewer.present(frame, self._frame_stats, PixelFormat.BGR)
        return False

    def get_video_rect(self, widget_rect: QRect) -> QRect:
        """Return the letter‑/pillarboxed rectangle for the current frame."""
        if self._frame_stats is None:
            return widget_rect
        v_h, v_w = self._frame_stats.shape[:2]
        return _aspect_rect(v_w, v_h, widget_rect)

    @property
    def min_resolution(self) -> Tuple[int, int]:
        return self._min_resolution

    # ── Geometry ──────────────────────────────────────────────────────

    def update_geometry(self, video_rect: QRect) -> None:
        """Position viewer and controls within the given video rectangle."""
        # Viewer fills the whole area
        self.viewer.setGeometry(video_rect)

        if self._frame_stats is not None:
            zoom = video_rect.width() / self._frame_stats.shape[1]
            self.settings.update_setting("zoom", zoom)

        # Controls at the bottom, centred, max 800 px wide
        controls_h = self.controls.sizeHint().height() or 80
        controls_w = min(800, video_rect.width() - 40)
        controls_x = video_rect.x() + (video_rect.width() - controls_w) // 2
        controls_y = video_rect.bottom() - controls_h - 20
        self.controls.setGeometry(controls_x, controls_y, controls_w,
                                  controls_h)

    # ── Playback pass‑throughs ────────────────────────────────────────

    def set_duration(self, duration_ms: int) -> None:
        self.controls.set_duration(duration_ms)

    def set_position(self, position_ms: int) -> None:
        self.controls.set_position(position_ms)

    def set_playing_state(self, playing: bool) -> None:
        self.controls.set_playing_state(playing)


# ---------------------------------------------------------------------------
# 2. StackSubtitleManager  (subtitle label + file selector)
# ---------------------------------------------------------------------------

class SubtitleOverlayManager(QObject):
    """Manages the subtitle label and the file‑selector popup."""

    subtitle_changed = pyqtSignal(str)
    subtitle_font_changed = pyqtSignal(QFont)
    subtitle_outline_changed = pyqtSignal(QColor, int)
    subtitle_antialiasing_changed = pyqtSignal(bool)
    subtitle_background_opacity_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._subtitle_pos = SubtitlePosition.BOTTOM
        self._subtitle_offset = 0

        # Subtitle label
        self.subtitle_label = OutlineLabel(parent)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.subtitle_label.font()
        font.setPointSize(40)
        font.setBold(True)
        self.subtitle_label.setFont(font)
        self.subtitle_label.set_background_color(QColor("white"))
        self.subtitle_label.set_outline_color(QColor("black"))
        self.subtitle_label.set_outline_width(1)
        self.subtitle_label.set_antialiasing(True)
        self.subtitle_label.set_background_opacity(0.0)
        self.subtitle_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.subtitle_label.hide()

        # File selector (independent popup)
        self.panel = SubtitleSettingsDialog()
        self.panel.subtitle_file_selected.connect(
            self.subtitle_changed
        )

        self.panel.subtitle_position_changed.connect(
            self.set_subtitle_position)
        self.panel.subtitle_offset_changed.connect(
            self.set_subtitle_offset)
        self.panel.subtitle_style_changed.connect(self._apply_style)

    @pyqtSlot(SubtitleStyle)
    def _apply_style(self, style: SubtitleStyle) -> None:
        """Translate a SubtitleStyle snapshot into individual manager calls."""
        font = self.subtitle_label.font()
        font.setFamily(style.font_family)
        font.setPointSize(style.font_size)
        font.setBold(style.bold)
        self.set_subtitle_font(font)  # emits subtitle_font_changed
        self.set_subtitle_text_color(QColor(style.text_color))
        self.set_subtitle_outline(
            QColor(style.outline_color), style.outline_width
            # emits subtitle_outline_changed
        )
        self.set_subtitle_background_opacity(
            style.background_opacity)  # emits signal
        self.set_subtitle_antialiasing(style.antialiasing)

        # ── Geometry ──────────────────────────────────────────────────────

    def update_geometry(self, video_rect: QRect) -> None:
        """Position the subtitle label inside the video rectangle."""
        if not self.subtitle_label.isVisible():
            return
        self.subtitle_label.setFixedWidth(video_rect.width() - 40)
        self.subtitle_label.adjustSize()

        x = video_rect.x() + (
                video_rect.width() - self.subtitle_label.width()
        ) // 2

        if self._subtitle_pos == SubtitlePosition.TOP:
            y = video_rect.y() + self._subtitle_offset
        elif self._subtitle_pos == SubtitlePosition.BOTTOM:
            y = (
                    video_rect.bottom()
                    - self.subtitle_label.height()
                    - self._subtitle_offset
            )
        else:  # centre fallback
            y = video_rect.y() + (
                    video_rect.height() - self.subtitle_label.height()
            ) // 2

        self.subtitle_label.move(x, y)

    # ── Text display ──────────────────────────────────────────────────

    def set_subtitle_text(self, text: str) -> None:
        if not text:
            self.subtitle_label.hide()
        else:
            self.subtitle_label.setText(text)
            self.subtitle_label.show()

    def set_subtitle_position(
            self, position: SubtitlePosition
    ) -> None:
        self._subtitle_pos = position

    def set_subtitle_offset(self, offset: int = 0):
        self._subtitle_offset = offset

    # ── Font ──────────────────────────────────────────────────────────

    def set_subtitle_font(self, font: QFont) -> None:
        self.subtitle_label.setFont(font)
        self.subtitle_font_changed.emit(font)

    def set_subtitle_font_size(self, point_size: int) -> None:
        font = self.subtitle_label.font()
        font.setPointSize(point_size)
        self.set_subtitle_font(font)

    # ── Styling ───────────────────────────────────────────────────────

    def set_subtitle_antialiasing(self, enabled: bool) -> None:
        self.subtitle_label.set_antialiasing(enabled)
        self.subtitle_antialiasing_changed.emit(enabled)

    def set_subtitle_outline(
            self, color: QColor, width: int | None = None
    ) -> None:
        if width is not None:
            self.subtitle_label.set_outline_width(width)
        self.subtitle_label.set_outline_color(color)
        self.subtitle_outline_changed.emit(
            color, self.subtitle_label.outline_width
        )

    def set_subtitle_outline_color(self, color: QColor) -> None:
        self.set_subtitle_outline(color)

    def set_subtitle_outline_width(self, width: int) -> None:
        self.subtitle_label.set_outline_width(width)
        self.subtitle_outline_changed.emit(
            self.subtitle_label.outline_color, width
        )

    def set_subtitle_background_opacity(self, opacity: float) -> None:
        self.subtitle_label.set_background_opacity(opacity)
        self.subtitle_background_opacity_changed.emit(opacity)

    def set_subtitle_background_color(self, color: QColor) -> None:
        self.subtitle_label.set_background_color(color)

    def set_subtitle_text_color(self, color: QColor) -> None:
        palette = self.subtitle_label.palette()
        palette.setColor(self.subtitle_label.foregroundRole(), color)
        self.subtitle_label.setPalette(palette)

    def get_subtitle_settings(self) -> dict:
        lbl = self.subtitle_label
        return {
            "font": lbl.font(),
            "font_size": lbl.font().pointSize(),
            "outline_color": lbl.outline_color,
            "outline_width": lbl.outline_width,
            "antialiasing": lbl.antialiasing,
            "background_opacity": lbl.background_opacity,
            "background_color": lbl.background_color,
            "text_color": lbl.palette().color(lbl.foregroundRole()),
        }

    # ── File selector popup ──────────────────────────────────────────

    @pyqtSlot(bool)
    def toggle_panel(self, checked: bool) -> None:
        if checked:
            self.panel.show_centered()
        else:
            self.panel.hide_panel()


# ---------------------------------------------------------------------------
# 3. VideoPlayerStack  (composite, purely coordinates the managers)
# ---------------------------------------------------------------------------

class VideoPlayerStack(QWidget):
    """
    Composite video player widget.

    Layers (back → front):
        1. viewer         — OpenGL frame display
        2. subtitle_label — transparent outline label
        3. controls       — translucent transport controls
        4. settings_widget— floating settings panel (auto‑managed)

    All signals from the managers are re‑emitted at this level.
    """

    # ── Playback signals ──────────────────────────────────────────────
    play_pause_clicked = pyqtSignal(bool)
    forward_clicked = pyqtSignal()
    backward_clicked = pyqtSignal()
    reverse_clicked = pyqtSignal(bool)
    seek_requested = pyqtSignal(int)
    volume_changed = pyqtSignal(float)

    # ── Subtitle signals ─────────────────────────────────────────────
    subtitle_changed = pyqtSignal(str)
    subtitle_font_changed = pyqtSignal(QFont)
    subtitle_outline_changed = pyqtSignal(QColor, int)
    subtitle_antialiasing_changed = pyqtSignal(bool)
    subtitle_background_opacity_changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        QSurfaceFormat.setDefaultFormat(get_surface_format())
        self.setMouseTracking(True)
        self.setObjectName("overlayStack")
        self.setStyleSheet(
            "QWidget#overlayStack { background-color: black; }"
        )

        # Shared image settings (used by viewer and settings panel)
        self.settings = ImageSettings()
        self.settings.interpolation = False

        # Create the two managers
        self._video_manager = VideoOverlayManager(self.settings, self)
        self._subtitle_manager = SubtitleOverlayManager(self)

        # Forward all manager signals to the stack’s own signals
        self._connect_manager_signals()

        # Wire cross‑cutting toggles (controls → popups)
        self._video_manager.subtitle_requested.connect(
            self._subtitle_manager.toggle_panel
            )

    def _connect_manager_signals(self) -> None:
        vm = self._video_manager
        vm.play_pause_clicked.connect(self.play_pause_clicked)
        vm.forward_clicked.connect(self.forward_clicked)
        vm.backward_clicked.connect(self.backward_clicked)
        vm.reverse_clicked.connect(self.reverse_clicked)
        vm.seek_requested.connect(self.seek_requested)
        vm.volume_changed.connect(self.volume_changed)

        vm.panel.dialog_closed.connect(lambda:
                                       vm.controls.settings_btn.setChecked(False))

        sm = self._subtitle_manager
        sm.subtitle_changed.connect(self.subtitle_changed)

        sm.subtitle_font_changed.connect(self.subtitle_font_changed)
        sm.subtitle_outline_changed.connect(self.subtitle_outline_changed)
        sm.subtitle_antialiasing_changed.connect(
            self.subtitle_antialiasing_changed
        )
        sm.subtitle_background_opacity_changed.connect(
            self.subtitle_background_opacity_changed
        )



        panel = sm.panel
        # Position and offset directly move the label — geometry must refresh.
        panel.subtitle_position_changed.connect(self._update_geometry)
        panel.subtitle_offset_changed.connect(self._update_geometry)
        # Font-size changes alter label height — geometry must refresh too.
        sm.subtitle_font_changed.connect(self._update_geometry)

        panel.dialog_closed.connect(lambda:
                                    self._video_manager.controls.subtitle_btn.setChecked(False))

    # ── Qt events ───────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_geometry()

    def _update_geometry(self) -> None:
        video_rect = self._video_manager.get_video_rect(self.rect())
        min_res = self._video_manager.min_resolution
        if video_rect.width() < min_res[0] or video_rect.height() < min_res[1]:
            logger.debug(
                "Skipping geometry update — video rect %dx%d below minimum %dx%d",
                video_rect.width(), video_rect.height(), *min_res,
            )
            return
        self._video_manager.update_geometry(video_rect)
        self._subtitle_manager.update_geometry(video_rect)

    # ── Frame ingestion ─────────────────────────────────────────────

    def set_frame(self, frame: np.ndarray) -> None:
        size_changed = self._video_manager.set_frame(frame)
        if size_changed:
            self.setMinimumSize(*self._video_manager.min_resolution)
            self._update_geometry()

    # ── Playback pass‑throughs ──────────────────────────────────────

    def set_duration(self, duration_ms: int) -> None:
        self._video_manager.set_duration(duration_ms)

    def set_position(self, position_ms: int) -> None:
        self._video_manager.set_position(position_ms)

    def set_playing_state(self, playing: bool) -> None:
        self._video_manager.set_playing_state(playing)

    # ── Subtitle pass‑throughs (all delegates to subtitle manager) ──

    def set_subtitle_text(self, text: str) -> None:
        self._subtitle_manager.set_subtitle_text(text)
        self._update_geometry()

    def set_subtitle_position(
            self,
            position: SubtitlePosition = SubtitlePosition.BOTTOM,
            offset: int = 0,
    ) -> None:
        self._subtitle_manager.set_subtitle_position(position)
        self._update_geometry()

    def set_subtitle_offset(
            self,
            offset: int = 0,
    ) -> None:
        self._subtitle_manager.set_subtitle_offset(offset)
        self._update_geometry()

    def set_subtitle_font(self, font: QFont) -> None:
        self._subtitle_manager.set_subtitle_font(font)
        self._update_geometry()

    def set_subtitle_font_size(self, point_size: int) -> None:
        self._subtitle_manager.set_subtitle_font_size(point_size)
        self._update_geometry()

    def set_subtitle_antialiasing(self, enabled: bool) -> None:
        self._subtitle_manager.set_subtitle_antialiasing(enabled)

    def set_subtitle_outline(
            self, color: QColor, width: int | None = None
    ) -> None:
        self._subtitle_manager.set_subtitle_outline(color, width)

    def set_subtitle_outline_color(self, color: QColor) -> None:
        self._subtitle_manager.set_subtitle_outline_color(color)

    def set_subtitle_outline_width(self, width: int) -> None:
        self._subtitle_manager.set_subtitle_outline_width(width)

    def set_subtitle_background_opacity(self, opacity: float) -> None:
        self._subtitle_manager.set_subtitle_background_opacity(opacity)

    def set_subtitle_background_color(self, color: QColor) -> None:
        self._subtitle_manager.set_subtitle_background_color(color)

    def set_subtitle_text_color(self, color: QColor) -> None:
        self._subtitle_manager.set_subtitle_text_color(color)

    def get_subtitle_settings(self) -> dict:
        return self._subtitle_manager.get_subtitle_settings()
