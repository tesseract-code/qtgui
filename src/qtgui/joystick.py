__all__ = ['Direction', 'JoystickMove', 'JoystickWidget',
           'KeyboardJoystickMixin', 'compute_joystick_displacement']

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import NamedTuple, List, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent,
                         QPen, QRadialGradient, QKeyEvent)
from PyQt6.QtWidgets import QWidget


class Direction(Enum):
    """Directional constants for joystick movements."""
    UP = auto()
    UP_RIGHT = auto()
    RIGHT = auto()
    DOWN_RIGHT = auto()
    DOWN = auto()
    DOWN_LEFT = auto()
    LEFT = auto()
    UP_LEFT = auto()
    NONE = auto()


# Angle ranges for 8 directions (center angle, half-span = 22.5°)
# These angles are in SCREEN coordinates: 0° = right, 90° = up, 180° = left, 270° = down
_DIRECTION_ANGLES: dict[Direction, float] = {
    Direction.RIGHT: 0.0,
    Direction.UP_RIGHT: 45.0,
    Direction.UP: 90.0,
    Direction.UP_LEFT: 135.0,
    Direction.LEFT: 180.0,
    Direction.DOWN_LEFT: 225.0,
    Direction.DOWN: 270.0,
    Direction.DOWN_RIGHT: 315.0,
}


@dataclass(frozen=True)
class JoystickMove:
    """Immutable data class representing a joystick movement."""
    direction: Direction
    step_size: float
    angle: float  # In radians, screen coordinates (0 = right, pi/2 = up, pi = left, 3pi/2 = down)

    def __str__(self) -> str:
        return f"Move({self.direction.name}, step={self.step_size:.2f}, angle={math.degrees(self.angle):.1f}°)"


class ButtonState(NamedTuple):
    """State tuple for button rendering."""
    hovered: bool
    pressed: bool


type ColorTuple = tuple[int, int, int, int]  # Python 3.12 type alias


class DirectionalButton:
    """Represents a single directional button segment in the joystick."""

    def __init__(self, direction: Direction, start_angle: float, span_angle: float):
        self.direction = direction
        self.start_angle = start_angle  # In degrees
        self.span_angle = span_angle
        self.state = ButtonState(hovered=False, pressed=False)

    def contains_angle(self, angle: float) -> bool:
        """Check if an angle falls within this button's arc."""
        # Normalize angle to 0-360
        angle = angle % 360
        start = self.start_angle % 360
        end = (self.start_angle + self.span_angle) % 360

        if start <= end:
            return start <= angle < end
        else:  # Wraps around 0 (e.g., RIGHT: 315° to 45°)
            return angle >= start or angle < end

    def get_base_color(self) -> QColor:
        """Get the base color for this button based on direction."""
        return QColor(80, 227, 230, 255)


class KeyboardJoystickMixin:
    """
    Mixin to add keyboard arrow key support to joystick widget.

    The widget must have:
    - _button_map: dict[Direction, DirectionalButton]
    - button_pressed: pyqtSignal(Direction)
    - _add_move(direction: Direction, angle: float) method
    - update() method
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._keyboard_pressed_directions: set[Direction] = set()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard arrow keys for directional buttons."""
        key_to_direction = {
            Qt.Key.Key_Up: Direction.UP,
            Qt.Key.Key_Down: Direction.DOWN,
            Qt.Key.Key_Left: Direction.LEFT,
            Qt.Key.Key_Right: Direction.RIGHT,
        }

        key = event.key()

        if key in key_to_direction and not event.isAutoRepeat():
            direction = key_to_direction[key]

            # Add to pressed set
            self._keyboard_pressed_directions.add(direction)

            # Update button state
            if direction in self._button_map:
                button = self._button_map[direction]
                button.state = ButtonState(button.state.hovered, True)

                # Emit signal and add move
                self.button_pressed.emit(direction)
                angle = _DIRECTION_ANGLES[direction]
                self._add_move(direction, angle)

                self.update()
                return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard arrow key releases."""
        key_to_direction = {
            Qt.Key.Key_Up: Direction.UP,
            Qt.Key.Key_Down: Direction.DOWN,
            Qt.Key.Key_Left: Direction.LEFT,
            Qt.Key.Key_Right: Direction.RIGHT,
        }

        key = event.key()

        if key in key_to_direction and not event.isAutoRepeat():
            direction = key_to_direction[key]

            # Remove from pressed set
            self._keyboard_pressed_directions.discard(direction)

            # Update button state
            if direction in self._button_map:
                button = self._button_map[direction]
                button.state = ButtonState(button.state.hovered, False)

                self.update()
                return

        super().keyReleaseEvent(event)


class JoystickWidget(KeyboardJoystickMixin, QWidget):
    """
    Advanced joystick widget with 4 directional buttons and center control.

    Features:
    - Modern, clean UI design with 4 cardinal buttons
    - Analog joystick supports 8 directions (including diagonals)
    - Continuous joystick control until mouse release
    - Full button hover and press states
    - Keyboard arrow key support via KeyboardJoystickMixin
    - Batched signal emission
    - Configurable step size

    Coordinate System:
    - Angles are in SCREEN coordinates: 0° = right, 90° = up, 180° = left, 270° = down
    - This matches Qt's coordinate system where Y increases downward
    - JoystickMove.angle uses this convention consistently
    """

    movements_batched = pyqtSignal(list)  # List[JoystickMove]
    button_pressed = pyqtSignal(Direction)

    def __init__(
        self,
        parent: QWidget | None = None,
        step_size: float = 1.0,
        batch_interval_ms: int = 50
    ):
        super().__init__(parent)

        self._step_size = step_size
        self._batch_interval_ms = batch_interval_ms

        self._joystick_pressed = False
        self._joystick_position = QPointF(0, 0)
        self._move_buffer: list[JoystickMove] = []
        self._pressed_button: DirectionalButton | None = None

        # 4 cardinal direction buttons (90° each)
        # Qt angles: 0° = 3 o'clock, positive = CCW
        self._buttons: list[DirectionalButton] = [
            DirectionalButton(Direction.RIGHT, -45, 90),   # Right: -45° to 45°
            DirectionalButton(Direction.UP, 45, 90),       # Up: 45° to 135°
            DirectionalButton(Direction.LEFT, 135, 90),    # Left: 135° to 225°
            DirectionalButton(Direction.DOWN, 225, 90),    # Down: 225° to 315°
        ]

        # Create a mapping for quick button lookup by direction
        self._button_map: dict[Direction, DirectionalButton] = {
            button.direction: button for button in self._buttons
        }

        self._batch_timer = QTimer()
        self._batch_timer.timeout.connect(self._emit_batched_moves)
        self._batch_timer.start(self._batch_interval_ms)

        self._continuous_timer = QTimer()
        self._continuous_timer.timeout.connect(self._emit_continuous_move)
        self._continuous_interval_ms = 50
        self._continuous_timer.setInterval(self._continuous_interval_ms)

        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def step_size(self) -> float:
        return self._step_size

    @step_size.setter
    def step_size(self, value: float) -> None:
        self._step_size = max(0.1, value)

    @property
    def batch_interval_ms(self) -> int:
        return self._batch_interval_ms

    @batch_interval_ms.setter
    def batch_interval_ms(self, value: int) -> None:
        self._batch_interval_ms = max(10, value)
        self._batch_timer.setInterval(self._batch_interval_ms)

    def _get_center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def _get_radius(self) -> float:
        return min(self.width(), self.height()) / 2 - 20

    def _point_to_angle(self, point: QPointF) -> float:
        """
        Convert a point to an angle in degrees using SCREEN coordinates.

        Returns: angle where 0° = right, 90° = up, 180° = left, 270° = down
        """
        center = self._get_center()
        dx = point.x() - center.x()
        dy = center.y() - point.y()  # Invert Y for screen coords
        angle = math.degrees(math.atan2(dy, dx))
        return (angle + 360) % 360

    def _angle_to_direction(self, angle: float) -> Direction:
        """Convert an angle (in screen coordinates) to one of 8 directions."""
        # Normalize to 0-360
        angle = (angle + 360) % 360

        # 8 directions, 45° each, boundaries at 22.5° offsets
        if angle < 22.5 or angle >= 337.5:
            return Direction.RIGHT
        elif angle < 67.5:
            return Direction.UP_RIGHT
        elif angle < 112.5:
            return Direction.UP
        elif angle < 157.5:
            return Direction.UP_LEFT
        elif angle < 202.5:
            return Direction.LEFT
        elif angle < 247.5:
            return Direction.DOWN_LEFT
        elif angle < 292.5:
            return Direction.DOWN
        else:
            return Direction.DOWN_RIGHT

    def _find_button_at_point(self, point: QPointF) -> DirectionalButton | None:
        """Find which button contains the given point."""
        center = self._get_center()
        distance = math.hypot(point.x() - center.x(), point.y() - center.y())
        radius = self._get_radius()
        joystick_radius = radius * 0.4

        if distance < joystick_radius or distance > radius:
            return None

        angle = self._point_to_angle(point)

        for button in self._buttons:
            if button.contains_angle(angle):
                return button

        return None

    def _is_in_joystick_area(self, point: QPointF) -> bool:
        """Check if point is in the center joystick area."""
        center = self._get_center()
        distance = math.hypot(point.x() - center.x(), point.y() - center.y())
        radius = self._get_radius()
        joystick_radius = radius * 0.4
        return distance <= joystick_radius

    def _is_joystick_displaced(self) -> bool:
        """Check if joystick is currently displaced from center."""
        distance = math.hypot(self._joystick_position.x(), self._joystick_position.y())
        return distance > 5  # Dead zone

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        if self._is_in_joystick_area(pos):
            self._joystick_pressed = True
            self._update_joystick_position(pos)
            if self._is_joystick_displaced():
                self._continuous_timer.start()
            self.update()
            return

        button = self._find_button_at_point(pos)
        if button:
            self._pressed_button = button
            button.state = ButtonState(button.state.hovered, True)
            self.button_pressed.emit(button.direction)
            self._add_move(button.direction, self._point_to_angle(pos))
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        if self._joystick_pressed:
            self._update_joystick_position(pos)
            if self._is_joystick_displaced():
                if not self._continuous_timer.isActive():
                    self._continuous_timer.start()
            else:
                self._continuous_timer.stop()
            self.update()
            return

        if self._pressed_button is not None:
            new_button = self._find_button_at_point(pos)

            for button in self._buttons:
                is_pressed = button is new_button
                is_hovered = button is new_button
                button.state = ButtonState(is_hovered, is_pressed)

            if new_button and new_button is not self._pressed_button:
                self._pressed_button = new_button
                self.button_pressed.emit(new_button.direction)
                self._add_move(new_button.direction, self._point_to_angle(pos))

            self.update()
            return

        hovered_button = self._find_button_at_point(pos)

        for button in self._buttons:
            new_hovered = button is hovered_button
            button.state = ButtonState(new_hovered, button.state.pressed)

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._joystick_pressed:
            self._joystick_pressed = False
            self._joystick_position = QPointF(0, 0)
            self._continuous_timer.stop()
            self.update()

        self._pressed_button = None
        for button in self._buttons:
            button.state = ButtonState(button.state.hovered, False)

        self.update()

    def _update_joystick_position(self, pos: QPointF) -> None:
        """Update joystick position and queue move based on current offset."""
        center = self._get_center()
        radius = self._get_radius()
        max_offset = radius * 0.3

        offset = QPointF(pos.x() - center.x(), pos.y() - center.y())
        distance = math.hypot(offset.x(), offset.y())

        # Clamp to max offset
        if distance > max_offset:
            scale = max_offset / distance
            offset = QPointF(offset.x() * scale, offset.y() * scale)
            distance = max_offset

        self._joystick_position = offset

    def _emit_continuous_move(self) -> None:
        """Emit move based on current joystick position."""
        if not self._joystick_pressed:
            return

        offset = self._joystick_position
        distance = math.hypot(offset.x(), offset.y())

        if distance <= 5:  # Dead zone
            return

        radius = self._get_radius()
        max_offset = radius * 0.3

        # Calculate angle in SCREEN coordinates
        # offset.x() > 0 means right, offset.y() > 0 means down (screen coords)
        # We want: 0° = right, 90° = up, so invert Y
        angle_rad = math.atan2(-offset.y(), offset.x())
        angle_deg = (math.degrees(angle_rad) + 360) % 360
        direction = self._angle_to_direction(angle_deg)

        # Scale step size by displacement intensity
        intensity = distance / max_offset

        move = JoystickMove(
            direction=direction,
            step_size=self._step_size * intensity,
            angle=angle_rad
        )
        self._move_buffer.append(move)

        # Debug: uncomment to verify values are changing
        # print(f"offset=({offset.x():.1f}, {offset.y():.1f}) angle={angle_deg:.1f}° dir={direction.name}")

    def _add_move(self, direction: Direction, angle: float) -> None:
        """Add a move to the buffer."""
        move = JoystickMove(
            direction=direction,
            step_size=self._step_size,
            angle=math.radians(angle)
        )
        self._move_buffer.append(move)

    def _emit_batched_moves(self) -> None:
        """Emit batched moves and clear buffer."""
        if self._move_buffer:
            self.movements_batched.emit(self._move_buffer.copy())
            self._move_buffer.clear()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        center = self._get_center()
        radius = self._get_radius()

        self._draw_outer_glow(painter, center, radius)

        for button in self._buttons:
            self._draw_button(painter, center, radius, button)

        for button in self._buttons:
            self._draw_arrow(painter, center, radius, button)

        self._draw_joystick_base(painter, center, radius)
        self._draw_joystick(painter, center, radius)

    def _draw_outer_glow(self, painter: QPainter, center: QPointF, radius: float) -> None:
        glow_radius = radius + 10

        glow_gradient = QRadialGradient(center, glow_radius)
        glow_gradient.setColorAt(0.85, QColor(80, 227, 230, 0))
        glow_gradient.setColorAt(0.95, QColor(80, 227, 230, 100))
        glow_gradient.setColorAt(1.0, QColor(80, 227, 230, 0))

        painter.setBrush(glow_gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(
            center.x() - glow_radius, center.y() - glow_radius,
            glow_radius * 2, glow_radius * 2
        ))

        painter.setPen(QPen(QColor(80, 227, 230, 255), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(
            center.x() - radius, center.y() - radius,
            radius * 2, radius * 2
        ))

    def _draw_button(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        button: DirectionalButton
    ) -> None:
        inner_radius = radius * 0.45

        path = QPainterPath()
        rect = QRectF(
            center.x() - radius, center.y() - radius,
            radius * 2, radius * 2
        )
        path.arcMoveTo(rect, button.start_angle)
        path.arcTo(rect, button.start_angle, button.span_angle)

        inner_rect = QRectF(
            center.x() - inner_radius, center.y() - inner_radius,
            inner_radius * 2, inner_radius * 2
        )
        end_angle = button.start_angle + button.span_angle
        path.arcTo(inner_rect, end_angle, -button.span_angle)
        path.closeSubpath()

        base_color = QColor(44, 62, 80)

        if button.state.pressed:
            fill_color = QColor(30, 42, 56)
        elif button.state.hovered:
            fill_color = QColor(52, 73, 94)
        else:
            fill_color = base_color

        painter.fillPath(path, fill_color)

        if button.state.pressed:
            painter.setPen(QPen(QColor(20, 28, 38), 2))
            painter.drawPath(path)

        painter.setPen(QPen(QColor(30, 42, 56), 1))
        painter.drawPath(path)

    def _draw_arrow(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        button: DirectionalButton
    ) -> None:
        mid_angle = math.radians(button.start_angle + button.span_angle / 2)
        arrow_distance = radius * 0.72

        arrow_center = QPointF(
            center.x() + math.cos(mid_angle) * arrow_distance,
            center.y() - math.sin(mid_angle) * arrow_distance
        )

        arrow_size = 12
        arrow_angle = mid_angle

        tip = QPointF(
            arrow_center.x() + math.cos(arrow_angle) * arrow_size,
            arrow_center.y() - math.sin(arrow_angle) * arrow_size
        )

        left_base = QPointF(
            arrow_center.x() + math.cos(arrow_angle - 0.8) * arrow_size * 0.6,
            arrow_center.y() - math.sin(arrow_angle - 0.8) * arrow_size * 0.6
        )

        right_base = QPointF(
            arrow_center.x() + math.cos(arrow_angle + 0.8) * arrow_size * 0.6,
            arrow_center.y() - math.sin(arrow_angle + 0.8) * arrow_size * 0.6
        )

        if button.state.pressed:
            arrow_color = QColor(80, 227, 230, 255)
        elif button.state.hovered:
            arrow_color = QColor(80, 227, 230, 200)
        else:
            arrow_color = QColor(80, 227, 230, 120)

        pen = QPen(arrow_color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        path.moveTo(left_base)
        path.lineTo(tip)
        path.lineTo(right_base)
        painter.drawPath(path)

    def _draw_joystick_base(self, painter: QPainter, center: QPointF, radius: float) -> None:
        base_radius = radius * 0.4

        recess_gradient = QRadialGradient(center, base_radius)
        recess_gradient.setColorAt(0, QColor(30, 42, 56))
        recess_gradient.setColorAt(0.7, QColor(35, 48, 64))
        recess_gradient.setColorAt(1, QColor(44, 62, 80))

        painter.setBrush(recess_gradient)
        pen = QPen(QColor(20, 28, 38), 2)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(
            center.x() - base_radius, center.y() - base_radius,
            base_radius * 2, base_radius * 2
        ))

    def _draw_joystick(self, painter: QPainter, center: QPointF, radius: float) -> None:
        joystick_radius = radius * 0.3

        joystick_center = QPointF(
            center.x() + self._joystick_position.x(),
            center.y() + self._joystick_position.y()
        )

        outer_gradient = QRadialGradient(
            joystick_center.x() - joystick_radius * 0.3,
            joystick_center.y() - joystick_radius * 0.3,
            joystick_radius * 1.5
        )

        if self._joystick_pressed:
            outer_gradient.setColorAt(0, QColor(50, 70, 90))
            outer_gradient.setColorAt(1, QColor(35, 48, 64))
        else:
            outer_gradient.setColorAt(0, QColor(60, 80, 100))
            outer_gradient.setColorAt(1, QColor(44, 62, 80))

        painter.setBrush(outer_gradient)
        painter.setPen(QPen(QColor(30, 42, 56), 2))
        painter.drawEllipse(QRectF(
            joystick_center.x() - joystick_radius,
            joystick_center.y() - joystick_radius,
            joystick_radius * 2, joystick_radius * 2
        ))

        inner_radius = joystick_radius * 0.5

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(80, 227, 230, 255), 3))
        painter.drawEllipse(QRectF(
            joystick_center.x() - inner_radius,
            joystick_center.y() - inner_radius,
            inner_radius * 2, inner_radius * 2
        ))

        dot_radius = joystick_radius * 0.15
        painter.setBrush(QColor(80, 227, 230, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(
            joystick_center.x() - dot_radius,
            joystick_center.y() - dot_radius,
            dot_radius * 2, dot_radius * 2
        ))


def compute_joystick_displacement(moves: List["JoystickMove"]
                                  ) -> Tuple[float, float]:
        """
        Compute total displacement from a batch of joystick moves using vectorized ops.

        The joystick provides angles in SCREEN coordinates:
        - 0° = right (positive X)
        - 90° = up (negative Y in screen coords)
        - 180° = left (negative X)
        - 270° = down (positive Y in screen coords)

        Returns:
            tuple (dx, dy) of total displacement in screen coordinates
        """
        if not moves:
            return 0, 0

        # Apply each move sequentially
        total_dx = 0
        total_dy = 0
        for move in moves:
            dx = 0
            dy = 0

            # Calculate movement based on direction and step size
            match move.direction:
                case Direction.UP:
                    dy = -move.step_size
                case Direction.DOWN:
                    dy = move.step_size
                case Direction.LEFT:
                    dx = -move.step_size
                case Direction.RIGHT:
                    dx = move.step_size
                case Direction.UP_LEFT:
                    dx = move.step_size * math.cos(move.angle)
                    dy = -move.step_size * math.sin(move.angle)
                case Direction.UP_RIGHT:
                    dx = move.step_size * math.cos(move.angle)
                    dy = -move.step_size * math.sin(move.angle)
                case Direction.DOWN_LEFT:
                    dx = move.step_size * math.cos(move.angle)
                    dy = -move.step_size * math.sin(move.angle)
                case Direction.DOWN_RIGHT:
                    dx = move.step_size * math.cos(move.angle)
                    dy = -move.step_size * math.sin(move.angle)
                case _:
                    continue

            total_dx += dx
            total_dy += dy

        return total_dx, total_dy