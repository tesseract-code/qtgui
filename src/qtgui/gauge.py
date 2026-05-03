"""
Classical Gauge Widget for PyQt6
"""
import math
from typing import List, Optional
from dataclasses import dataclass
from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import pyqtSignal, QPropertyAnimation, QEasingCurve, QRectF, \
    QPointF, QTimer


@dataclass
class ColorZone:
    """Defines a color zone on the gauge."""
    start_value: float
    end_value: float
    color: str
    label: str = ""


@dataclass
class GaugeTheme:
    """Theme configuration for the gauge."""
    background_color: str = "#F8F9FA"
    needle_color: str = "#DC3545"
    text_color: str = "#212529"
    scale_color: str = "#6C757D"
    border_color: str = "#DEE2E6"
    center_color: str = "#495057"
    zone_alpha: int = 120  # Transparency for color zones
    glow_color: str = "#3498DB"


class AnalogGauge(QtWidgets.QWidget):
    """
    Classical gauge widget with 270° arc layout.

    Uses mathematical coordinates with Y-axis flipped via QPainter transformation.
    Layout: 270° span from 225° (7 o'clock) clockwise to 315° (5 o'clock)
    Value mapping: min_value -> 225°, max_value -> 315° (270° clockwise arc)
    """

    # Signals
    value_changed = pyqtSignal(float)
    target_reached = pyqtSignal(float)
    zone_entered = pyqtSignal(ColorZone)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        # Core properties
        self._value = 0.0
        self._min_value = 0.0
        self._max_value = 100.0
        self._target_value = 0.0

        # Theme
        self._theme = GaugeTheme()

        # Gauge geometry (270° clockwise arc in mathematical coordinates)
        # With Y-axis flipped via transformation, this becomes clockwise visually
        self._start_angle = 225.0  # 7 o'clock position (min_value) - SW quadrant
        self._end_angle = 315.0  # 5 o'clock position (max_value) - SE quadrant
        self._span_angle = -270.0  # 270° clockwise span (going the long way around)
        self._needle_length_ratio = 0.75
        self._needle_width = 3

        # Display options
        self._show_value = True
        self._show_labels = True
        self._show_ticks = True
        self._precision = 1
        self._units = ""

        # Tick configuration
        self._major_tick_count = 6
        self._minor_ticks_per_major = 4
        self._major_tick_length = 15
        self._minor_tick_length = 8

        # Color zones
        self._color_zones: List[ColorZone] = []
        self._current_zone: Optional[ColorZone] = None

        # Animation properties
        self._animate_value_changes = True
        self._animation_duration = 800  # milliseconds
        self._animation_easing = QEasingCurve.Type.OutQuart
        self._glow_enabled = False
        self._glow_intensity = 0.0

        # Geometry cache
        self._gauge_rect = QRectF()
        self._center_point = QPointF()
        self._radius = 0.0

        # Setup animations
        self._value_animation = QPropertyAnimation(self, b"animated_value")
        self._value_animation.setDuration(self._animation_duration)
        self._value_animation.setEasingCurve(self._animation_easing)
        self._value_animation.valueChanged.connect(
            self._on_animation_value_changed)
        self._value_animation.finished.connect(self._on_animation_finished)

        # Glow animation
        self._glow_animation = QPropertyAnimation(self, b"glow_intensity")
        self._glow_animation.setDuration(2000)
        self._glow_animation.setLoopCount(-1)  # Infinite loop
        self._glow_animation.setStartValue(0.0)
        self._glow_animation.setEndValue(1.0)
        self._glow_animation.setEasingCurve(QEasingCurve.Type.InOutSine)

        # Widget setup
        self.setMinimumSize(200, 200)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding
        )

        self._update_geometry()
        self._update_current_zone()

    # Properties
    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, val: float) -> None:
        """Set gauge value with optional animation."""
        val = max(self._min_value, min(self._max_value, val))

        if abs(val - self._value) > 1e-6:  # Use epsilon for float comparison
            old_value = self._value

            if (self._animate_value_changes and
                    self._value_animation.state() == QPropertyAnimation.State.Stopped):
                self._target_value = val
                self._value_animation.setStartValue(old_value)
                self._value_animation.setEndValue(val)
                self._value_animation.start()
            else:
                self._value = val
                self._update_current_zone()
                self.update()
                self.value_changed.emit(val)

    @property
    def min_value(self) -> float:
        return self._min_value

    @min_value.setter
    def min_value(self, val: float) -> None:
        if val != self._min_value and val < self._max_value:
            self._min_value = float(val)
            if self._value < val:
                self.value = val
            self.update()

    @property
    def max_value(self) -> float:
        return self._max_value

    @max_value.setter
    def max_value(self, val: float) -> None:
        if val != self._max_value and val > self._min_value:
            self._max_value = float(val)
            if self._value > val:
                self.value = val
            self.update()

    # Animation properties for QPropertyAnimation
    def get_animated_value(self) -> float:
        return self._value

    def set_animated_value(self, val: float) -> None:
        self._value = val
        self._update_current_zone()
        self.update()

    animated_value = QtCore.pyqtProperty(float, get_animated_value,
                                         set_animated_value)

    def get_glow_intensity(self) -> float:
        return self._glow_intensity

    def set_glow_intensity(self, intensity: float) -> None:
        self._glow_intensity = max(0.0, min(1.0, intensity))
        if self._glow_enabled:
            self.update()

    glow_intensity = QtCore.pyqtProperty(float, get_glow_intensity,
                                         set_glow_intensity)

    # Configuration methods
    def set_range(self, min_val: float, max_val: float) -> None:
        """Set gauge range."""
        if min_val >= max_val:
            raise ValueError("min_value must be less than max_value")

        self._min_value = float(min_val)
        self._max_value = float(max_val)

        # Clamp current value to new range
        if self._value < min_val:
            self.value = min_val
        elif self._value > max_val:
            self.value = max_val

        self._update_current_zone()
        self.update()

    def add_color_zone(self, start: float, end: float, color: str,
                       label: str = "") -> None:
        """Add a color zone."""
        if start >= end:
            raise ValueError("Zone start must be less than end")

        zone = ColorZone(float(start), float(end), color, label)
        self._color_zones.append(zone)
        self._color_zones.sort(key=lambda z: z.start_value)
        self._update_current_zone()
        self.update()

    def clear_color_zones(self) -> None:
        """Clear all color zones."""
        self._color_zones.clear()
        self._current_zone = None
        self.update()

    def set_animation_enabled(self, enabled: bool) -> None:
        """Enable or disable value change animations."""
        self._animate_value_changes = enabled

    def set_animation_duration(self, duration: int) -> None:
        """Set animation duration in milliseconds."""
        self._animation_duration = duration
        self._value_animation.setDuration(duration)

    def set_glow_enabled(self, enabled: bool) -> None:
        """Enable or disable glow effect with proper cleanup."""
        self._glow_enabled = bool(enabled)
        if enabled:
            if self._glow_animation.state() == QPropertyAnimation.State.Stopped:
                self._glow_animation.start()
        else:
            self._glow_animation.stop()
            self._glow_intensity = 0.0
        self.update()

    def set_display_options(
            self,
            show_value: bool = True,
            show_labels: bool = True,
            show_ticks: bool = True,
            precision: int = 1,
            units: str = ""
    ) -> None:
        """Configure display options."""
        self._show_value = show_value
        self._show_labels = show_labels
        self._show_ticks = show_ticks
        self._precision = precision
        self._units = units
        self.update()

    def set_needle_style(self, length_ratio: float = 0.75,
                         width: int = 3) -> None:
        """Configure needle appearance."""
        self._needle_length_ratio = max(0.1, min(1.0, length_ratio))
        self._needle_width = max(1, width)
        self.update()

    def set_theme(self, theme: GaugeTheme) -> None:
        """Set custom theme."""
        self._theme = theme
        self.update()

    # Internal methods
    def _update_geometry(self) -> None:
        """Update internal geometry calculations."""
        widget_rect = self.rect()
        if widget_rect.isEmpty():
            return

        # Calculate square gauge area with margins
        margin = 20
        available_size = min(widget_rect.width(),
                             widget_rect.height()) - 2 * margin

        # Center the gauge
        self._gauge_rect = QRectF(
            widget_rect.center().x() - available_size / 2,
            widget_rect.center().y() - available_size / 2,
            available_size,
            available_size
        )

        self._center_point = self._gauge_rect.center()
        self._radius = available_size / 2 - 15  # Leave space for labels

    def _update_current_zone(self) -> None:
        """Update the current color zone."""
        old_zone = self._current_zone
        self._current_zone = None

        for zone in self._color_zones:
            if zone.start_value <= self._value <= zone.end_value:
                self._current_zone = zone
                break

        if self._current_zone != old_zone and self._current_zone:
            self.zone_entered.emit(self._current_zone)

    def _on_animation_value_changed(self, value: float) -> None:
        """Handle animation value changes."""
        if value is not None:
            self._update_current_zone()
            self.value_changed.emit(value)

    def _on_animation_finished(self) -> None:
        """Handle animation completion."""
        self.target_reached.emit(self._target_value)

    def _value_to_angle(self, value: float) -> float:
        """
        Convert gauge value to angle in degrees.
        Maps from min_value->225° to max_value->315° (90° clockwise span)
        """
        if abs(self._max_value - self._min_value) < 1e-10:
            return self._start_angle

        # Calculate ratio of value in range
        ratio = (value - self._min_value) / (self._max_value - self._min_value)

        # Map to angle: start at 225°, end at 315° (90° clockwise)
        # Going clockwise means adding positive degrees
        angle = self._start_angle + (ratio * self._span_angle)

        # Normalize to 0-360 range
        angle = angle % 360

        return angle

    def _qt_angle(self, degrees: float) -> int:
        """Convert degrees to Qt's 1/16th degree units."""
        return int(degrees * 16)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """Handle resize events."""
        super().resizeEvent(event)
        self._update_geometry()
        self.update()

    # Drawing methods
    def _draw_background(self, painter: QtGui.QPainter) -> None:
        """Draw gauge background centered at (0,0)."""
        # Glow effect
        if self._glow_enabled and self._glow_intensity > 0:
            glow_color = QtGui.QColor(self._theme.glow_color)
            glow_color.setAlphaF(0.3 * self._glow_intensity)
            glow_pen = QtGui.QPen(glow_color, 8)
            painter.setPen(glow_pen)
        else:
            painter.setPen(
                QtGui.QPen(QtGui.QColor(self._theme.border_color), 2))

        painter.setBrush(
            QtGui.QBrush(QtGui.QColor(self._theme.background_color)))

        # Draw circle centered at (0, 0)
        painter.drawEllipse(QPointF(0, 0), self._radius, self._radius)

    def _draw_color_zones(self, painter: QtGui.QPainter) -> None:
        """Draw color zones using Qt's native coordinate system."""
        if not self._color_zones:
            return

        # Save the current transformation and reset to Qt coordinates
        painter.save()
        painter.resetTransform()

        # Zone radius (slightly smaller than gauge)
        zone_margin = 12
        zone_radius = self._radius - zone_margin

        # Zone rectangle in Qt coordinates (centered at self._center_point)
        zone_rect = QRectF(
            self._center_point.x() - zone_radius,
            self._center_point.y() - zone_radius,
            2 * zone_radius,
            2 * zone_radius
        )


        painter.setPen(QtCore.Qt.PenStyle.NoPen)

        for zone in self._color_zones:
            # Clamp zone to gauge range
            zone_start = max(zone.start_value, self._min_value)
            zone_end = min(zone.end_value, self._max_value)

            if zone_start >= zone_end:
                continue

            # Convert values to mathematical angles
            math_start = self._value_to_angle(zone_start)
            math_end = self._value_to_angle(zone_end)

            # Convert from math coordinates (Y-up) to Qt coordinates (Y-down)
            # Formula: qt_angle = (360 - math_angle) % 360
            # But for drawPie, we also need to account for how it measures angles
            # In Qt: 0° = 3 o'clock, positive = counter-clockwise
            # But with Y-down, this means visually: 0° = 3 o'clock, 90° = 6 o'clock, etc.
            #
            # To mirror across X-axis: qt_angle = -math_angle = (360 - math_angle) % 360
            qt_start = (math_start) % 360.0
            qt_end = (math_end) % 360.0

            # Calculate span going from start to end
            # Since math_end < math_start (values increase, angles decrease)
            # qt_end > qt_start
            # We want to draw clockwise (in visual terms) from start to end
            # In Qt's Y-down system, clockwise is negative span
            span = qt_end - qt_start
            # We want the negative span (clockwise visual direction)
            if span > 0:
                span = span - 360.0

            # Skip tiny zones
            if abs(span) < 0.5:
                continue

            # Set zone color with transparency
            color = QtGui.QColor(zone.color)
            color.setAlpha(self._theme.zone_alpha)
            painter.setBrush(QtGui.QBrush(color))

            # Draw the arc zone
            painter.drawPie(
                zone_rect,
                self._qt_angle(qt_start),
                self._qt_angle(span)
            )

        # Restore transformation
        painter.restore()

    def _draw_ticks_and_labels(self, painter: QtGui.QPainter) -> None:
        """Draw ticks and labels using mathematical coordinates."""
        if not (self._show_ticks or self._show_labels):
            return

        # Calculate tick values
        if self._major_tick_count <= 1:
            return

        value_range = self._max_value - self._min_value
        major_step = value_range / (self._major_tick_count - 1)

        # Font for labels (flip text back to normal orientation)
        font = painter.font()
        font.setPointSize(max(8, int(self._radius / 20)))
        font.setBold(True)
        painter.setFont(font)

        # Tick positioning - align with zone boundary
        zone_margin = 12
        tick_outer_radius = self._radius - zone_margin  # Start at zone edge
        major_tick_inner_radius = tick_outer_radius - self._major_tick_length
        minor_tick_inner_radius = tick_outer_radius - self._minor_tick_length

        # Draw major ticks and labels
        for i in range(self._major_tick_count):
            value = self._min_value + (i * major_step)

            # Get angle and convert to radians
            qt_angle_deg = self._value_to_angle(value)
            angle_rad = math.radians(qt_angle_deg)

            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            if self._show_ticks:
                # Major tick
                outer_point = QPointF(
                    tick_outer_radius * cos_a,
                    tick_outer_radius * sin_a
                )
                inner_point = QPointF(
                    major_tick_inner_radius * cos_a,
                    major_tick_inner_radius * sin_a
                )
                painter.setPen(
                    QtGui.QPen(QtGui.QColor(self._theme.scale_color), 2))
                painter.drawLine(outer_point, inner_point)

            if self._show_labels:
                # Label positioning - inside the ticks
                label_radius = major_tick_inner_radius - 10
                label_center = QPointF(
                    label_radius * cos_a,
                    label_radius * sin_a
                )

                # Format label text
                if abs(value - round(value)) < 1e-10:
                    text = str(int(value))
                else:
                    text = f"{value:.{self._precision}f}"

                # Save state for text orientation
                painter.save()
                # Move to label position and flip text right-side up
                painter.translate(label_center)
                painter.scale(1.0, -1.0)

                # Draw label
                painter.setPen(
                    QtGui.QPen(QtGui.QColor(self._theme.text_color), 1))
                fm = painter.fontMetrics()
                text_rect = fm.boundingRect(text)
                text_pos = QPointF(
                    -text_rect.width() / 2,
                    text_rect.height() / 4
                )
                painter.drawText(text_pos, text)
                painter.restore()

            # Draw minor ticks
            if self._show_ticks and i < self._major_tick_count - 1:
                minor_step = major_step / (self._minor_ticks_per_major + 1)
                for j in range(1, self._minor_ticks_per_major + 1):
                    minor_value = value + (j * minor_step)
                    if minor_value > self._max_value:
                        break

                    minor_angle_deg = self._value_to_angle(minor_value)
                    minor_angle_rad = math.radians(minor_angle_deg)

                    minor_cos = math.cos(minor_angle_rad)
                    minor_sin = math.sin(minor_angle_rad)

                    outer_point = QPointF(
                        tick_outer_radius * minor_cos,
                        tick_outer_radius * minor_sin
                    )
                    inner_point = QPointF(
                        minor_tick_inner_radius * minor_cos,
                        minor_tick_inner_radius * minor_sin
                    )

                    painter.setPen(
                        QtGui.QPen(QtGui.QColor(self._theme.scale_color), 1))
                    painter.drawLine(outer_point, inner_point)

    def _draw_needle(self, painter: QtGui.QPainter) -> None:
        """Draw the needle using mathematical coordinates."""
        # Get needle angle
        qt_angle_deg = self._value_to_angle(self._value)
        angle_rad = math.radians(qt_angle_deg)

        needle_length = self._radius * self._needle_length_ratio
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        # Needle tip
        tip_point = QPointF(
            needle_length * cos_a,
            needle_length * sin_a
        )

        # Needle base (perpendicular to needle direction)
        base_width = self._needle_width
        perp_angle1 = angle_rad + math.pi / 2
        perp_angle2 = angle_rad - math.pi / 2

        base1 = QPointF(
            base_width * math.cos(perp_angle1),
            base_width * math.sin(perp_angle1)
        )
        base2 = QPointF(
            base_width * math.cos(perp_angle2),
            base_width * math.sin(perp_angle2)
        )

        # Needle tail
        tail_length = 20
        tail_point = QPointF(
            -tail_length * cos_a,
            -tail_length * sin_a
        )

        # Needle color (use zone color if in a zone)
        needle_color = QtGui.QColor(self._theme.needle_color)
        if self._current_zone:
            needle_color = QtGui.QColor(self._current_zone.color)

        # Draw needle shadow
        shadow_offset = 2
        shadow_color = QtGui.QColor(0, 0, 0, 30)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(shadow_color))

        shadow_polygon = QtGui.QPolygonF([
            QPointF(tip_point.x() + shadow_offset,
                    tip_point.y() + shadow_offset),
            QPointF(base1.x() + shadow_offset, base1.y() + shadow_offset),
            QPointF(tail_point.x() + shadow_offset,
                    tail_point.y() + shadow_offset),
            QPointF(base2.x() + shadow_offset, base2.y() + shadow_offset)
        ])
        painter.drawPolygon(shadow_polygon)

        # Draw needle
        painter.setBrush(QtGui.QBrush(needle_color))
        painter.setPen(QtGui.QPen(needle_color.darker(120), 1))

        needle_polygon = QtGui.QPolygonF([tip_point, base1, tail_point, base2])
        painter.drawPolygon(needle_polygon)

        # Center hub
        hub_radius = 8
        center_color = QtGui.QColor(self._theme.center_color)
        painter.setBrush(QtGui.QBrush(center_color))
        painter.setPen(QtGui.QPen(center_color.darker(150), 2))
        painter.drawEllipse(QPointF(0, 0), hub_radius, hub_radius)

    def _draw_value_display(self, painter: QtGui.QPainter) -> None:
        """Draw current value display."""
        if not self._show_value:
            return

        # Format value
        if abs(self._value - round(self._value)) < 1e-10:
            value_text = str(int(self._value))
        else:
            value_text = f"{self._value:.{self._precision}f}"

        if self._units:
            value_text += f" {self._units}"

        # Position and style
        font = painter.font()
        font.setPointSize(max(12, int(self._radius / 12)))
        font.setBold(True)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_rect = fm.boundingRect(value_text)

        # Position below center
        text_pos = QPointF(
            self._center_point.x() - text_rect.width() / 2,
            self._center_point.y() + self._radius * 0.5
        )

        # Draw text
        painter.setPen(QtGui.QPen(QtGui.QColor(self._theme.text_color), 1))
        painter.drawText(text_pos, value_text)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Main paint method using transformation matrix."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)

        # Ensure geometry is current
        if self._gauge_rect.isEmpty():
            self._update_geometry()

        # Set up coordinate transformation
        # Translate to center and flip Y-axis for mathematical coordinates
        painter.translate(self._center_point.x(), self._center_point.y())
        painter.scale(1.0, -1.0)  # Flip Y-axis: now positive Y goes up

        # Draw components in order (now using (0,0) as center)
        self._draw_background(painter)
        self._draw_color_zones(painter)
        self._draw_ticks_and_labels(painter)
        self._draw_needle(painter)

        # Reset transformation for value display (needs normal text orientation)
        painter.resetTransform()
        self._draw_value_display(painter)

    def sizeHint(self) -> QtCore.QSize:
        """Preferred size."""
        return QtCore.QSize(300, 300)

    def minimumSizeHint(self) -> QtCore.QSize:
        """Minimum size."""
        return QtCore.QSize(150, 150)
