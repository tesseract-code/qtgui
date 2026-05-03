import logging
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Tuple, List

from PyQt6 import QtGui
from PyQt6.QtCore import (QTimer, pyqtSignal, Qt, QSize, QPoint,
                          QEvent)
from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
from PyQt6.QtWidgets import QLabel, QWidget, QMainWindow, QSlider, QApplication
from PyQt6.QtWidgets import QVBoxLayout

logger = logging.getLogger(__name__)


class SliderHandleType(Enum):
    """Enum for slider handle types."""
    LOW = "low"
    HIGH = "high"
    SPAN = "span"


class ValueDisplayMode(Enum):
    """Enum for value display modes."""
    NUMERIC = "numeric"
    TIME = "time"
    CUSTOM = "custom"


class RangeSlider(QWidget):
    """
    Float-based multi-thumb range slider with floating labels.
    Supports numeric values, time series data, and custom formatting.
    """

    rangeChanged = pyqtSignal(float, float)
    sliderPressed = pyqtSignal()
    sliderReleased = pyqtSignal()
    actionTriggered = pyqtSignal(int)

    _start_win_resize_timer = pyqtSignal()
    _start_label_update_timer = pyqtSignal()

    # Import QSlider constants for compatibility
    NoTicks = QSlider.TickPosition.NoTicks
    TicksAbove = QSlider.TickPosition.TicksAbove
    TicksLeft = QSlider.TickPosition.TicksLeft
    TicksBelow = QSlider.TickPosition.TicksBelow
    TicksRight = QSlider.TickPosition.TicksRight
    TicksBothSides = QSlider.TickPosition.TicksBothSides

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(parent)

        self._orientation: Qt.Orientation = orientation

        # Float range - not constrained to integers
        self._min_val: float = 0.0
        self._max_val: float = 100.0
        self._low: float = 0.0
        self._high: float = 100.0
        self._page_step: float = 10.0
        self._single_step: float = 1.0

        # NEW: Prevent min/max from being the same by default
        self._allow_collapse: bool = False

        # Visual constants
        self._handle_radius: int = 6

        # Tick mark configuration
        self._tick_position: QSlider.TickPosition = QSlider.TickPosition.NoTicks
        self._tick_interval: float = 0.0  # 0 means use tick count
        self._tick_count: int = 2  # Minimum 2 ticks (start and end)

        # Visual properties
        self._inverted_appearance = False
        self._inverted_controls = False

        # Dragging state
        self._drag_handle: Optional[SliderHandleType] = None
        self._is_dragging: bool = False
        self._drag_offset: float = 0.0
        self._tracking: bool = True

        # Label configuration
        self._labels_visible: bool = True
        self._force_label_update: bool = False
        self._label_precision: int = 1
        self._display_mode: ValueDisplayMode = ValueDisplayMode.NUMERIC
        self._custom_formatter: Optional[Callable[[float], str]] = None
        self._time_format: str = "%H:%M:%S"
        self._time_reference: Optional[
            float] = None  # For absolute time display

        # Label positioning
        self._label_offset: int = 8  # Space between handle and label
        self._min_label_spacing: int = 5  # Minimum space between labels to avoid overlap

        # Tooltip-style labels
        self._low_label = QLabel()
        self._high_label = QLabel()
        self._setup_labels()
        self._low_label.setFont(
            QtGui.QFontDatabase.systemFont(
                QtGui.QFontDatabase.SystemFont.FixedFont
            )
        )
        self._high_label.setFont(
            QtGui.QFontDatabase.systemFont(
                QtGui.QFontDatabase.SystemFont.FixedFont
            )
        )

        # Performance optimization
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._delayed_update)
        self._pending_update = False

        self._label_update_timer = QTimer()
        self._label_update_timer.setSingleShot(True)
        self._label_update_timer.timeout.connect(self._update_label_positions)
        self._pending_label_update = False

        self._signal_throttle_timer = QTimer()
        self._signal_throttle_timer.setSingleShot(True)
        self._signal_throttle_timer.timeout.connect(self._emit_throttled_range)
        self._pending_range_signal = None

        # NEW: Timer for main window resize events
        self._window_resize_timer = QTimer()
        self._window_resize_timer.setSingleShot(True)
        self._window_resize_timer.timeout.connect(
            self._on_window_resize_finished)
        self._window_resizing = False

        # Throttle intervals (milliseconds)
        self._PAINT_THROTTLE_MS = 16  # ~60 FPS
        self._LABEL_THROTTLE_MS = 30  # ~30 FPS for labels
        self._SIGNAL_THROTTLE_MS = 50  # 20 signals per second max
        self._WINDOW_RESIZE_THROTTLE_MS = 100  # Wait for resize to finish

        self._start_label_update_timer.connect(
            lambda: self._label_update_timer.start(
                self._LABEL_THROTTLE_MS))

        self._start_win_resize_timer.connect(
            lambda: self._window_resize_timer.start(
                self._WINDOW_RESIZE_THROTTLE_MS))

        # Track last values to avoid redundant updates
        self._last_low = self._low
        self._last_high = self._high
        self._last_size = QSize()
        self._last_pos = QPoint()

        # NEW: Track main window for resize events
        self._main_window = None
        self._find_and_monitor_main_window()

        # Set minimum size to accommodate handles and labels
        self.setMinimumHeight(self._handle_radius * 2 + 20)
        self.setContentsMargins(10, 10, 10, 10)

    def _setup_labels(self):
        """Setup the tooltip-style labels with solid background"""
        for label in [self._low_label, self._high_label]:
            label.setStyleSheet("""
                QLabel {
                    background: palette(base);
                    border: 1px solid #888;
                    border-radius: 3px;
                    padding: 2px 6px;
                    color: palette(text);
                    font-weight: bold;
                }
            """)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.hide()
            # Use ToolTip flag to ensure they stay on top
            label.setWindowFlags(
                Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def _find_and_monitor_main_window(self):
        """Find the main window and install event filter to monitor resize events"""
        # Find the main window by walking up the parent hierarchy
        parent = self.parent()
        while parent and not isinstance(parent, QMainWindow):
            parent = parent.parent()

        if parent and isinstance(parent, QMainWindow):
            self._main_window = parent
            self._main_window.installEventFilter(self)
            logger.debug(
                f"Monitoring main window for resize events: {self._main_window}")

    # def event(self, event):
    #     event_type = event.type()
    #     # Handle window state changes and resize events
    #     if (event_type in [QEvent.Type.Resize]):
    #         # print(obj, event, self._window_resizing)
    #
    #         # Hide labels during resize/move operations
    #         if not self._window_resizing:
    #             self._low_label.hide()
    #             self._high_label.hide()
    #             self._window_resizing = True
    #
    #         # Restart the timer - we'll show labels when resize finishes
    #         self._start_win_resize_timer.emit()
    #     return super().event(event)

    def eventFilter(self, obj, event):
        """Event filter to catch main window resize, maximize, minimize, and move events"""
        if obj != self:
            event_type = event.type()

            # Handle window state changes and resize events
            if (event_type in [QEvent.Type.Resize,
                               QEvent.Type.Show,
                               QEvent.Type.Hide,
                               QEvent.Type.Move,
                               QEvent.Type.WindowStateChange]):

                # Hide labels during resize/move operations
                if not self._window_resizing:
                    self._low_label.hide()
                    self._high_label.hide()
                    #     self._window_resizing = True
                    self._LABEL_THROTTLE_MS = 1000

                # Restart the timer - we'll show labels when resize finishes
                self._start_win_resize_timer.emit()

        return super().eventFilter(obj, event)

    def _on_window_resize_finished(self):
        """Called when window resize/move operation is complete"""
        self._window_resizing = False
        self._labels_visible = True
        self._force_label_update = True
        if self.isVisible():
            self._request_label_update()

    def showEvent(self, event):
        """Ensure labels are properly parented when shown"""
        super().showEvent(event)
        # Reparent labels to ensure they're above other widget
        if self.parent():
            self._low_label.setParent(self.parent())
            self._high_label.setParent(self.parent())

        # Re-find main window if needed
        if not self._main_window:
            self._find_and_monitor_main_window()

        # Update labels when shown
        if self._labels_visible:
            self._low_label.show()
            self._high_label.show()
            self._request_label_update()

    def hideEvent(self, event):
        """Hide labels when slider is hidden"""
        self._low_label.hide()
        self._high_label.hide()
        super().hideEvent(event)

    def _update_label_positions(self):
        """Update the position and content of floating labels"""
        self._pending_label_update = False

        # Don't update labels during window resize or if not visible
        if not self.isVisible() or self._window_resizing:
            self._low_label.hide()
            self._high_label.hide()
            return
        else:
            self._LABEL_THROTTLE_MS = 30

        # Only update if values actually changed
        if (self._low == self._last_low and
                self._high == self._last_high and
                self._last_size == self.size() and
                self._last_pos == self.pos() and
                not self._force_label_update):
            return

        self._force_label_update = False
        low_pos = self._value_to_pixel(self._low)
        high_pos = self._value_to_pixel(self._high)

        # Format label texts
        low_text = self._format_value(self._low)
        high_text = self._format_value(self._high)

        self._low_label.setText(low_text)
        self._high_label.setText(high_text)

        # Update label sizes
        self._low_label.adjustSize()
        self._high_label.adjustSize()

        if self._orientation == Qt.Orientation.Horizontal:
            self._update_horizontal_labels(low_pos, high_pos)
        else:
            self._update_vertical_labels(low_pos, high_pos)

        self._low_label.show()
        self._high_label.show()
        self._low_label.raise_()
        self._high_label.raise_()

        # Update last values
        self._last_low = self._low
        self._last_high = self._high

    def _request_label_update(self):
        """Throttled request for label position update"""
        if not self._pending_label_update and not self._window_resizing:
            self._pending_label_update = True
            self._start_label_update_timer.emit()

    def _update_horizontal_labels(self, low_pos, high_pos):
        """Update label positions for horizontal orientation - FIXED POSITIONING"""
        label_height = self._low_label.height()
        label_spacing = 2

        # Calculate Y position above the track (relative to parent)
        track_y = self.mapToParent(QPoint(0, self.height() // 2)).y()
        label_y = track_y - self._handle_radius - self._label_offset - label_height

        # Calculate X positions (relative to parent)
        low_label_x = self.mapToParent(
            QPoint(int(low_pos - self._low_label.width() // 2), 0)).x()
        high_label_x = self.mapToParent(
            QPoint(int(high_pos - self._high_label.width() // 2), 0)).x()

        # Avoid label collision
        if (low_label_x + self._low_label.width() + self._min_label_spacing >
                high_label_x):
            # Stack labels vertically
            self._low_label.move(int(low_label_x), int(label_y))
            self._high_label.move(int(high_label_x),
                                  int(label_y - label_height - label_spacing))
        else:
            # Place labels at same height
            self._low_label.move(int(low_label_x), int(label_y))
            self._high_label.move(int(high_label_x), int(label_y))

        # Ensure labels stay within parent bounds
        self._constrain_label_to_parent(self._low_label)
        self._constrain_label_to_parent(self._high_label)

    def _update_vertical_labels(self, low_pos, high_pos):
        """Update label positions for vertical orientation - CORRECTED"""
        label_width = max(self._low_label.width(), self._high_label.width())
        label_spacing = 2

        # Calculate X position to the right of the track (relative to parent)
        track_x = self.mapToParent(QPoint(self.width() // 2, 0)).x()
        label_x = track_x + self._handle_radius + self._label_offset

        # Calculate Y positions - CORRECTED: min at bottom, max at top
        # In vertical orientation, low value is at bottom, high value is at top
        low_label_y = self.mapToParent(
            QPoint(0, int(low_pos - self._low_label.height() // 2))).y()
        high_label_y = self.mapToParent(
            QPoint(0, int(high_pos - self._high_label.height() // 2))).y()

        # Avoid label collision
        if (
                abs(low_label_y - high_label_y) < self._low_label.height() + self._min_label_spacing):
            # Stack labels horizontally if they would overlap vertically
            self._low_label.move(int(label_x), int(low_label_y))
            self._high_label.move(int(label_x + label_width + label_spacing),
                                  int(high_label_y))
        else:
            # Place labels at same horizontal position
            self._low_label.move(int(label_x), int(low_label_y))
            self._high_label.move(int(label_x), int(high_label_y))

        # Ensure labels stay within parent bounds
        self._constrain_label_to_parent(self._low_label)
        self._constrain_label_to_parent(self._high_label)

    def _constrain_label_to_parent(self, label):
        """Ensure label stays within parent widget bounds using local coordinates"""
        if not self.parent():
            return

        parent_rect = self.parent().rect()
        label_rect = label.geometry()

        # Adjust X position
        if label_rect.left() < parent_rect.left():
            label.move(parent_rect.left(), label_rect.top())
        elif label_rect.right() > parent_rect.right():
            label.move(parent_rect.right() - label_rect.width(),
                       label_rect.top())

        # Adjust Y position
        if label_rect.top() < parent_rect.top():
            label.move(label_rect.left(), parent_rect.top())
        elif label_rect.bottom() > parent_rect.bottom():
            label.move(label_rect.left(),
                       parent_rect.bottom() - label_rect.height())

    def _raise_labels(self):
        """Ensure labels are on top"""
        self._low_label.raise_()
        self._high_label.raise_()

    # ============ Performance Optimized Methods ============

    def _delayed_update(self):
        """Perform the actual update after throttling"""
        self._pending_update = False
        super().update()

    def _emit_throttled_range(self):
        """Emit the throttled range signal"""
        if self._pending_range_signal:
            low, high = self._pending_range_signal
            self._pending_range_signal = None
            self.rangeChanged.emit(low, high)

    def update(self):
        """Throttled update method"""
        if not self._pending_update:
            self._pending_update = True
            self._update_timer.start(self._PAINT_THROTTLE_MS)

    # ============ Collapse Prevention API ============

    def setAllowCollapse(self, allow: bool):
        """Set whether min and max values can be the same."""
        self._allow_collapse = allow
        # Ensure current values comply with new setting
        self._clamp_current_values()
        self.update()

    def allowCollapse(self) -> bool:
        """Get whether min and max values can be the same."""
        return self._allow_collapse

    def _enforce_min_separation(self, low: float, high: float) -> Tuple[
        float, float]:
        """Ensure low and high values maintain minimum separation."""
        if self._allow_collapse:
            return low, high

        # Calculate minimum separation based on range and step
        range_span = self._max_val - self._min_val
        if range_span <= 0:
            return low, high

        # Use the larger of single_step or a small percentage of the range
        min_separation = max(self._single_step, range_span * 0.001)

        if high - low < min_separation:
            # Try to maintain the current center position
            center = (low + high) / 2
            low = center - min_separation / 2
            high = center + min_separation / 2

            # Clamp to valid range
            if low < self._min_val:
                low = self._min_val
                high = low + min_separation
            elif high > self._max_val:
                high = self._max_val
                low = high - min_separation

        return low, high

    # ============ Label Configuration API ============

    def setLabelsVisible(self, visible: bool):
        """Set whether floating labels are visible."""
        self._labels_visible = visible
        if visible and not self._window_resizing:
            self._request_label_update()
        else:
            self._low_label.hide()
            self._high_label.hide()
        self.update()

    def labelsVisible(self) -> bool:
        """Get whether floating labels are visible."""
        return self._labels_visible

    def setLabelPrecision(self, precision: int):
        """Set decimal precision for numeric display."""
        self._label_precision = max(0, precision)
        self._request_label_update()
        self.update()

    def labelPrecision(self) -> int:
        """Get current label precision."""
        return self._label_precision

    def setDisplayMode(self, mode: ValueDisplayMode):
        """Set value display mode (numeric, time, or custom)."""
        self._display_mode = mode
        self._request_label_update()
        self.update()

    def displayMode(self) -> ValueDisplayMode:
        """Get current display mode."""
        return self._display_mode

    def setCustomFormatter(self, formatter: Callable[[float], str]):
        """Set custom formatting function for values."""
        self._custom_formatter = formatter
        self._request_label_update()
        self.update()

    def setTimeFormat(self, time_format: str):
        """Set time format string (strftime format)."""
        self._time_format = time_format
        self._request_label_update()
        self.update()

    def timeFormat(self) -> str:
        """Get current time format."""
        return self._time_format

    def setTimeReference(self, reference_timestamp: Optional[float]):
        """Set reference timestamp for absolute time display."""
        self._time_reference = reference_timestamp
        self._request_label_update()
        self.update()

    def timeReference(self) -> Optional[float]:
        """Get current time reference."""
        return self._time_reference

    # ============ Value Formatting ============

    def _format_value(self, value: float) -> str:
        """Format value based on current display mode."""
        if self._display_mode == ValueDisplayMode.NUMERIC:
            return self._format_numeric(value)
        elif self._display_mode == ValueDisplayMode.TIME:
            return self._format_time(value)
        elif self._display_mode == ValueDisplayMode.CUSTOM and self._custom_formatter:
            return self._custom_formatter(value)
        else:
            return self._format_numeric(value)  # Fallback

    def _format_numeric(self, value: float) -> str:
        """Format numeric value with current precision."""
        if self._label_precision == 0:
            return f"{int(round(value))}"
        else:
            return f"{value:.{self._label_precision}f}"

    def _format_time(self, value: float) -> str:
        """Format value as time string."""
        try:
            if self._time_reference is not None:
                # Absolute time: value is timestamp relative to reference
                timestamp = self._time_reference + value
                dt = datetime.fromtimestamp(timestamp)
            else:
                # Relative time: value is seconds since midnight or similar
                # Convert float seconds to time
                total_seconds = int(value)
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60

                # Handle milliseconds if needed
                if self._label_precision > 0:
                    milliseconds = int((value - total_seconds) * 1000)
                    dt = datetime(2000, 1, 1, hours, minutes, seconds,
                                  milliseconds * 1000)
                else:
                    dt = datetime(2000, 1, 1, hours, minutes, seconds)

            return dt.strftime(self._time_format)
        except (ValueError, OverflowError):
            return self._format_numeric(value)  # Fallback to numeric

    # ============ Public API (QSlider Parity) ============

    def orientation(self) -> Qt.Orientation:
        """Get slider orientation."""
        return self._orientation

    def setOrientation(self, orientation: Qt.Orientation):
        """Set slider orientation."""
        self._orientation = orientation
        self.update()

    def minimum(self) -> float:
        """Get minimum value of range."""
        return self._min_val

    def setMinimum(self, value: float):
        """Set minimum value."""
        self.setRange(float(value), self._max_val)

    def maximum(self) -> float:
        """Get maximum value of range."""
        return self._max_val

    def setMaximum(self, value: float):
        """Set maximum value."""
        self.setRange(self._min_val, float(value))

    def setRange(self, min_val: float, max_val: float):
        """Set the overall range of the slider."""
        min_val, max_val = float(min_val), float(max_val)

        if max_val < min_val:
            min_val, max_val = max_val, min_val

        self._min_val = min_val
        self._max_val = max_val
        self._clamp_current_values()
        self.update()

    def setValues(self, low: float, high: float):
        """Set current selected range values."""
        low, high = float(low), float(high)

        if low > high:
            low, high = high, low

        # Enforce minimum separation
        if not self._allow_collapse:
            low, high = self._enforce_min_separation(low, high)

        self._low = max(self._min_val, min(low, self._max_val))
        self._high = max(self._min_val, min(high, self._max_val))

        # Ensure minimum separation (redundant but safe)
        if not self._allow_collapse and self._high - self._low < self._single_step:
            self._high = self._low + self._single_step
            if self._high > self._max_val:
                self._high = self._max_val
                self._low = self._high - self._single_step

        self.update()

        if not self._is_dragging:
            self.rangeChanged.emit(self._low, self._high)

    def values(self) -> Tuple[float, float]:
        """Get current selected range values."""
        return (self._low, self._high)

    def singleStep(self) -> float:
        """Get single step value."""
        return self._single_step

    def setSingleStep(self, step: float):
        """Set single step value."""
        self._single_step = max(0.0, float(step))

    def pageStep(self) -> float:
        """Get page step value."""
        return self._page_step

    def setPageStep(self, step: float):
        """Set page step value."""
        self._page_step = max(0.0, float(step))

    def hasTracking(self) -> bool:
        """Check if tracking is enabled."""
        return self._tracking

    def setTracking(self, enable: bool):
        """Set tracking mode."""
        self._tracking = enable

    def invertedAppearance(self) -> bool:
        """Check if appearance is inverted."""
        return self._inverted_appearance

    def setInvertedAppearance(self, inverted: bool):
        """Set inverted appearance."""
        self._inverted_appearance = inverted
        self.update()

    def invertedControls(self) -> bool:
        """Check if controls are inverted."""
        return self._inverted_controls

    def setInvertedControls(self, inverted: bool):
        """Set inverted controls."""
        self._inverted_controls = inverted

    # ============ Tick Mark API ============

    def tickPosition(self) -> QSlider.TickPosition:
        """Get tick position."""
        return self._tick_position

    def setTickPosition(self, position: QSlider.TickPosition):
        """Set tick position."""
        self._tick_position = QSlider.TickPosition(position)
        self.update()

    def tickInterval(self) -> float:
        """Get tick interval."""
        return self._tick_interval

    def setTickInterval(self, interval: float):
        """Set tick interval."""
        self._tick_interval = max(0.0, float(interval))
        self.update()

    def setTickCount(self, count: int):
        """Set number of tick marks (used when tickInterval is 0)."""
        self._tick_count = max(2, count)
        self.update()

    def tickCount(self) -> int:
        """Get tick count."""
        return self._tick_count

    # ============ Size Hints ============

    def sizeHint(self):
        """Provide size hint accounting for labels."""
        if self._orientation == Qt.Orientation.Horizontal:
            return QSize(200,
                         self._handle_radius * 2 + 25)  # Extra space for labels
        else:
            return QSize(self._handle_radius * 2 + 60,
                         200)  # Extra width for labels

    def minimumSizeHint(self):
        """Minimum size that fits handles and labels."""
        if self._orientation == Qt.Orientation.Horizontal:
            return QSize(80, self._handle_radius * 2 + 25)
        else:
            return QSize(self._handle_radius * 2 + 60, 80)

    # ============ Coordinate Conversion ============

    def _value_to_pixel(self, value: float) -> float:
        """
        Convert a value to pixel position (handle center).
        Track is inset by handle radius to ensure handles fit within widget.
        """
        range_span = self._max_val - self._min_val
        if range_span <= 0:
            return self._handle_radius if self._orientation == Qt.Orientation.Horizontal else self.height() - self._handle_radius

        fraction = (value - self._min_val) / range_span

        if self._orientation == Qt.Orientation.Horizontal:
            # Horizontal: track spans from handle_radius to (width - handle_radius)
            # This ensures handles are fully visible
            usable_width = self.width() - (2 * self._handle_radius)
            return self._handle_radius + (fraction * usable_width)
        else:
            # Vertical: track spans from handle_radius to (height - handle_radius)
            # Bottom to top: min at bottom (high y), max at top (low y)
            usable_height = self.height() - (2 * self._handle_radius)
            return self.height() - self._handle_radius - (
                    fraction * usable_height)

    def _pixel_to_value(self, pos) -> float:
        """Convert mouse position to value."""
        range_span = self._max_val - self._min_val
        if range_span <= 0:
            return self._min_val

        if self._orientation == Qt.Orientation.Horizontal:
            usable_width = self.width() - (2 * self._handle_radius)
            if usable_width <= 0:
                return self._min_val
            pixel_offset = pos.x() - self._handle_radius
            ratio = max(0.0, min(1.0, pixel_offset / usable_width))
        else:
            usable_height = self.height() - (2 * self._handle_radius)
            if usable_height <= 0:
                return self._min_val
            pixel_offset = (self.height() - self._handle_radius) - pos.y()
            ratio = max(0.0, min(1.0, pixel_offset / usable_height))

        if self._inverted_appearance:
            ratio = 1.0 - ratio

        return self._min_val + (ratio * range_span)

    # ============ Painting ============

    def paintEvent(self, event):
        """Paint the slider without labels (they're separate widget now)"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Color scheme
        track_color = QColor(200, 200, 200)
        tick_color = QColor(150, 150, 150)
        range_color = QColor(66, 133, 244)
        handle_color = QColor(Qt.GlobalColor.white)



        # Draw tick marks if enabled
        if self._tick_position != QSlider.TickPosition.NoTicks:
            self._draw_ticks(painter, tick_color)

        # Draw main track
        self._draw_track(painter, track_color)

        # Draw selected range
        self._draw_range(painter, range_color)

        # Draw handles
        self._draw_handles(painter, range_color, handle_color)

        # Update floating label positions (throttled)
        self._request_label_update()

    def _draw_track(self, painter: QPainter, color: QColor):
        """Draw the main slider track with handle padding."""
        painter.setPen(QPen(color, 2))

        if self._orientation == Qt.Orientation.Horizontal:
            track_y = self.height() // 2
            # Track is inset by handle radius to ensure handles fit
            start_x = self._handle_radius
            end_x = self.width() - self._handle_radius + 1
            painter.drawLine(int(start_x), track_y, int(end_x), track_y)
        else:
            track_x = self.width() // 2
            # Track is inset by handle radius to ensure handles fit
            start_y = self._handle_radius
            end_y = self.height() - self._handle_radius + 1
            painter.drawLine(track_x, int(start_y), track_x, int(end_y))

    def _draw_range(self, painter: QPainter, color: QColor):
        """Draw the selected range span."""
        low_pos = self._value_to_pixel(self._low)
        high_pos = self._value_to_pixel(self._high)

        painter.setPen(QPen(color, 4))

        if self._orientation == Qt.Orientation.Horizontal:
            track_y = self.height() // 2
            painter.drawLine(int(low_pos), track_y, int(high_pos), track_y)
        else:
            track_x = self.width() // 2
            painter.drawLine(track_x, int(high_pos), track_x, int(low_pos))

    def _draw_handles(self, painter: QPainter, fill_color: QColor,
                      border_color: QColor):
        """Draw the low and high handle circles."""
        low_pos = self._value_to_pixel(self._low)
        high_pos = self._value_to_pixel(self._high)

        painter.setBrush(QBrush(fill_color))
        painter.setPen(QPen(border_color, 2))

        if self._orientation == Qt.Orientation.Horizontal:
            center_y = self.height() // 2
            # Draw handles - they will fit within widget bounds due to track padding
            painter.drawEllipse(
                int((low_pos + 1) - self._handle_radius),
                center_y - self._handle_radius,
                self._handle_radius * 2,
                self._handle_radius * 2
            )
            painter.drawEllipse(
                int((high_pos - 1) - self._handle_radius),
                center_y - self._handle_radius,
                self._handle_radius * 2,
                self._handle_radius * 2
            )
        else:
            center_x = self.width() // 2
            painter.drawEllipse(
                center_x - self._handle_radius,
                int((low_pos - 1) - self._handle_radius),
                self._handle_radius * 2,
                self._handle_radius * 2
            )
            painter.drawEllipse(
                center_x - self._handle_radius,
                int((high_pos + 1) - self._handle_radius),
                self._handle_radius * 2,
                self._handle_radius * 2
            )

    def _draw_ticks(self, painter: QPainter, color: QColor):
        """Draw tick marks along the slider."""
        painter.setPen(QPen(color, 2))
        tick_values = self._calculate_tick_values()

        for i, tick_value in enumerate(tick_values):
            if i == 0:
                tick_value = self._min_val

            if i == len(tick_values) - 1:
                tick_value = self._max_val
            self._draw_single_tick(painter, tick_value)

    def _draw_single_tick(self, painter: QPainter, tick_value: float):
        """Draw a single tick mark at the specified value."""
        tick_pos = self._value_to_pixel(tick_value)
        tick_length = 8

        if self._orientation == Qt.Orientation.Horizontal:
            tick_x = int(tick_pos)
            track_y = self.height() // 2

            if self._tick_position in [QSlider.TickPosition.TicksAbove,
                                       QSlider.TickPosition.TicksBothSides]:
                painter.drawLine(tick_x, track_y - tick_length, tick_x, track_y)
            if self._tick_position in [QSlider.TickPosition.TicksBelow,
                                       QSlider.TickPosition.TicksBothSides]:
                painter.drawLine(tick_x, track_y, tick_x, track_y + tick_length)
        else:
            tick_y = int(tick_pos)
            track_x = self.width() // 2

            if self._tick_position in [QSlider.TickPosition.TicksLeft,
                                       QSlider.TickPosition.TicksBothSides]:
                painter.drawLine(track_x - tick_length, tick_y, track_x, tick_y)
            if self._tick_position in [QSlider.TickPosition.TicksRight,
                                       QSlider.TickPosition.TicksBothSides]:
                painter.drawLine(track_x, tick_y, track_x + tick_length, tick_y)

    def _calculate_tick_values(self) -> List[float]:
        """Calculate tick values based on interval or count."""
        range_span = self._max_val - self._min_val

        if range_span <= 0:
            return [self._min_val]

        if self._tick_interval > 0:
            num_intervals = max(1, int(range_span / self._tick_interval))
            effective_tick_count = num_intervals + 1
        else:
            effective_tick_count = max(2, self._tick_count)

        effective_tick_count = max(2, effective_tick_count)

        tick_values = []
        interval = range_span / (effective_tick_count - 1)

        for i in range(effective_tick_count):
            tick_value = self._min_val + (i * interval)
            tick_values.append(tick_value)

        tick_values[-1] = self._max_val

        return tick_values

    # ============ Mouse Interaction ============

    def mousePressEvent(self, event):
        """Handle mouse press."""
        self._drag_handle = self._get_handle_at_pos(event.pos())

        if self._drag_handle:
            self._is_dragging = True

            if self._drag_handle == SliderHandleType.SPAN:
                click_val = self._pixel_to_value(event.pos())
                self._drag_offset = click_val - self._low

            self.sliderPressed.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse drag with throttling."""
        if not self._drag_handle or not self._is_dragging:
            return

        val = self._pixel_to_value(event.pos())

        if self._drag_handle == SliderHandleType.LOW:
            # Use collapse prevention
            if self._allow_collapse:
                max_low = self._high
            else:
                max_low = self._high - self._single_step
            self._low = max(self._min_val, min(val, max_low))

        elif self._drag_handle == SliderHandleType.HIGH:
            # Use collapse prevention
            if self._allow_collapse:
                min_high = self._low
            else:
                min_high = self._low + self._single_step
            self._high = min(self._max_val, max(val, min_high))

        elif self._drag_handle == SliderHandleType.SPAN:
            # Use collapse prevention for span width
            if self._allow_collapse:
                min_span_width = 0.0
            else:
                min_span_width = self._single_step

            span_width = self._high - self._low
            if span_width < min_span_width:
                span_width = min_span_width

            new_low = val - self._drag_offset

            if new_low < self._min_val:
                new_low = self._min_val
            elif new_low + span_width > self._max_val:
                new_low = self._max_val - span_width

            self._low = new_low
            self._high = new_low + span_width

        self.update()

        # Throttle rangeChanged signals during drag
        if self._tracking:
            if not self._signal_throttle_timer.isActive():
                self.rangeChanged.emit(self._low, self._high)
                self._signal_throttle_timer.start(self._SIGNAL_THROTTLE_MS)
            else:
                self._pending_range_signal = (self._low, self._high)

        event.accept()

    def mouseReleaseEvent(self, event):
        """Handle mouse release."""
        if self._is_dragging:
            self._is_dragging = False

            # Ensure final signal is emitted
            if not self._tracking:
                self.rangeChanged.emit(self._low, self._high)
            elif self._pending_range_signal:
                self.rangeChanged.emit(*self._pending_range_signal)
                self._pending_range_signal = None

            # Show labels again after dragging
            if self._labels_visible and not self._window_resizing:
                self._request_label_update()

            self.sliderReleased.emit()
            self._drag_handle = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _get_handle_at_pos(self, pos):
        """Determine what was clicked."""
        low_pos = self._value_to_pixel(self._low)
        high_pos = self._value_to_pixel(self._high)

        click_tolerance = 10

        if self._orientation == Qt.Orientation.Horizontal:
            # Check handles first (priority)
            if abs(pos.x() - low_pos) < click_tolerance:
                return SliderHandleType.LOW
            elif abs(pos.x() - high_pos) < click_tolerance:
                return SliderHandleType.HIGH
            # Check span
            elif min(low_pos, high_pos) < pos.x() < max(low_pos, high_pos):
                return SliderHandleType.SPAN
        else:
            # Check handles first
            if abs(pos.y() - low_pos) < click_tolerance:
                return SliderHandleType.LOW
            elif abs(pos.y() - high_pos) < click_tolerance:
                return SliderHandleType.HIGH
            # Check span
            elif min(low_pos, high_pos) < pos.y() < max(low_pos, high_pos):
                return SliderHandleType.SPAN

        return None

    def _clamp_current_values(self):
        """Clamp current low/high values to the valid range."""
        self._low = max(self._min_val, min(self._low, self._max_val))
        self._high = max(self._min_val, min(self._high, self._max_val))

        if self._low > self._high:
            self._low, self._high = self._high, self._low

        # Use collapse prevention
        if not self._allow_collapse and self._high - self._low < self._single_step:
            self._high = self._low + self._single_step
            if self._high > self._max_val:
                self._high = self._max_val
                self._low = self._high - self._single_step

    def resizeEvent(self, event):
        """Handle resize and update label positions with throttling"""
        super().resizeEvent(event)
        # Only update labels if size actually changed significantly
        self._last_size = self.size()
        if not self._window_resizing:
            self._low_label.hide()
            self._high_label.hide()
            self._window_resizing = True
            self._force_label_update = True
            # self._LABEL_THROTTLE_MS = 1000

        # Restart the timer - we'll show labels when resize finishes
        self._start_win_resize_timer.emit()
        # self._force_label_update = True
        # self._request_label_update()

    def moveEvent(self, event):
        """Handle move and update label positions with throttling"""
        super().moveEvent(event)
        # Only update labels if position actually changed significantly
        if (abs(self._last_pos.x() - self.pos().x()) > 2 or
                abs(self._last_pos.y() - self.pos().y()) > 2):
            self._last_pos = self.pos()
            self._request_label_update()
