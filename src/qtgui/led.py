"""
Status Indicator Widget
Provides LED-style status indication with customizable colors and animations.
"""

from enum import Enum, auto
from typing import Optional

from PyQt6 import QtWidgets, QtGui, QtCore
from PyQt6.QtCore import pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve


class ConnectedStateEnum(Enum):
    """Enumeration for connection states."""
    DISCONNECTED = auto()
    CONNECTED = auto()
    UNKNOWN = auto()
    CONNECTING = auto()


class StatusIndicator(QtWidgets.QAbstractButton):
    """
    LED status indicator.
    """

    # Signals
    state_changed = pyqtSignal(ConnectedStateEnum)

    # Constants
    DEFAULT_SIZE = 16
    SCALED_SIZE = 1000.0
    # milliseconds
    ANIMATION_DURATION = 300
    PULSE_DURATION = 1000

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        # Initialize properties
        self._state = ConnectedStateEnum.DISCONNECTED
        self._animate_transitions = True
        self._pulse_enabled = False
        self._opacity = 1.0

        # Setup widget properties
        self.setMinimumSize(self.DEFAULT_SIZE, self.DEFAULT_SIZE)
        self.setMaximumSize(self.DEFAULT_SIZE * 2,
                            self.DEFAULT_SIZE * 2)  # Reasonable maximum
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.MinimumExpanding,
                           QtWidgets.QSizePolicy.Policy.MinimumExpanding)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setEnabled(False)  # Non-interactive by default

        # Color scheme with modern flat design colors
        self._color_schemes = {
            ConnectedStateEnum.DISCONNECTED: {
                'primary': QtGui.QColor('#E74C3C'),  # Modern red
                'secondary': QtGui.QColor('#C0392B'),  # Darker red
                'glow': QtGui.QColor('#E74C3C')
            },
            ConnectedStateEnum.CONNECTED: {
                'primary': QtGui.QColor('#2ECC71'),  # Modern green
                'secondary': QtGui.QColor('#27AE60'),  # Darker green
                'glow': QtGui.QColor('#2ECC71')
            },
            ConnectedStateEnum.UNKNOWN: {
                'primary': QtGui.QColor('#F39C12'),  # Modern orange
                'secondary': QtGui.QColor('#E67E22'),  # Darker orange
                'glow': QtGui.QColor('#F39C12')
            },
            ConnectedStateEnum.CONNECTING: {
                'primary': QtGui.QColor('#3498DB'),  # Modern blue
                'secondary': QtGui.QColor('#2980B9'),  # Darker blue
                'glow': QtGui.QColor('#3498DB')
            }
        }

        # Animation setup
        self._opacity_animation = QPropertyAnimation(self, b"opacity")
        self._opacity_animation.setDuration(self.ANIMATION_DURATION)
        self._opacity_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Pulse animation timer
        self._pulse_timer = QTimer()
        self._pulse_timer.timeout.connect(self._pulse_animation)
        self._pulse_direction = 1  # 1 for fade in, -1 for fade out

        self.setContentsMargins(0, 0, 0, 0)

        # Tooltip support
        self._update_tooltip()

    @property
    def state(self) -> ConnectedStateEnum:
        """Get the current state."""
        return self._state

    @state.setter
    def state(self, new_state: ConnectedStateEnum) -> None:
        """Set the state with optional animation."""
        if new_state != self._state:
            old_state = self._state
            self._state = new_state

            if self._animate_transitions:
                self._animate_state_change()
            else:
                self.update()

            self._update_tooltip()
            self._update_pulse_animation()
            self.state_changed.emit(new_state)

    def set_color_scheme(self, state: ConnectedStateEnum,
                         primary: str, secondary: str, glow: str) -> None:
        """Customize colors for a specific state."""
        self._color_schemes[state] = {
            'primary': QtGui.QColor(primary),
            'secondary': QtGui.QColor(secondary),
            'glow': QtGui.QColor(glow)
        }
        if state == self._state:
            self.update()

    def set_animation_enabled(self, enabled: bool) -> None:
        """Enable or disable transition animations."""
        self._animate_transitions = enabled

    def set_pulse_enabled(self, enabled: bool) -> None:
        """Enable or disable pulsing animation for active states."""
        self._pulse_enabled = enabled
        self._update_pulse_animation()

    def _update_pulse_animation(self) -> None:
        """Update pulse animation based on current state and settings."""
        should_pulse = (self._pulse_enabled and
                        self._state in [ConnectedStateEnum.CONNECTING,
                                        ConnectedStateEnum.UNKNOWN])

        if should_pulse and not self._pulse_timer.isActive():
            self._pulse_timer.start(self.PULSE_DURATION // 20)  # 50 FPS
        elif not should_pulse and self._pulse_timer.isActive():
            self._pulse_timer.stop()
            self._opacity = 1.0
            self.update()

    def _pulse_animation(self) -> None:
        """Handle pulse animation frame."""
        self._opacity += 0.05 * self._pulse_direction

        if self._opacity >= 1.0:
            self._opacity = 1.0
            self._pulse_direction = -1
        elif self._opacity <= 0.3:
            self._opacity = 0.3
            self._pulse_direction = 1

        self.update()

    def _animate_state_change(self) -> None:
        """Animate transition between states."""
        self._opacity_animation.setStartValue(0.0)
        self._opacity_animation.setEndValue(1.0)
        self._opacity_animation.finished.connect(self.update)
        self._opacity_animation.start()

    def _update_tooltip(self) -> None:
        """Update tooltip based on current state."""
        tooltips = {
            ConnectedStateEnum.DISCONNECTED: "Disconnected",
            ConnectedStateEnum.CONNECTED: "Connected",
            ConnectedStateEnum.UNKNOWN: "Connection Status Unknown",
            ConnectedStateEnum.CONNECTING: "Connecting..."
        }
        self.setToolTip(tooltips.get(self._state, "Unknown State"))

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    opacity = QtCore.pyqtProperty(float, get_opacity, set_opacity)

    def sizeHint(self) -> QtCore.QSize:
        """Provide size hint for layout management."""
        return QtCore.QSize(self.DEFAULT_SIZE, self.DEFAULT_SIZE)

    def minimumSizeHint(self) -> QtCore.QSize:
        """Provide minimum size hint."""
        return QtCore.QSize(12, 12)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the LED indicator with modern styling."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # Calculate dimensions - ensure we stay within bounds
        rect = self.rect()
        size = min(rect.width(), rect.height()) - 2  # Subtract 2px for margin
        center = rect.center()

        # Scale and translate
        painter.translate(center)
        scale_factor = size / self.SCALED_SIZE
        painter.scale(scale_factor, scale_factor)

        # Get colors for current state
        colors = self._color_schemes.get(self._state)
        if not colors:
            return

        # Apply opacity for animations
        primary_color = QtGui.QColor(colors['primary'])
        secondary_color = QtGui.QColor(colors['secondary'])
        primary_color.setAlphaF(self._opacity)
        secondary_color.setAlphaF(self._opacity)

        # Draw outer bezel (subtle 3D effect)
        bezel_gradient = QtGui.QRadialGradient(0, 0, 500)
        bezel_gradient.setColorAt(0, QtGui.QColor('#F0F0F0'))
        bezel_gradient.setColorAt(1, QtGui.QColor('#D0D0D0'))

        painter.setPen(QtGui.QPen(QtGui.QColor('#B0B0B0'), 2))
        painter.setBrush(bezel_gradient)
        painter.drawEllipse(-500, -500, 1000, 1000)

        # Draw inner LED with gradient
        led_gradient = QtGui.QRadialGradient(-150, -150, 600)
        led_gradient.setColorAt(0, primary_color)
        led_gradient.setColorAt(0.7, secondary_color)
        led_gradient.setColorAt(1, secondary_color.darker(150))

        painter.setPen(QtGui.QPen(secondary_color.darker(200), 1))
        painter.setBrush(led_gradient)
        painter.drawEllipse(-400, -400, 800, 800)

        # Add subtle glow effect for active states
        if self._state != ConnectedStateEnum.DISCONNECTED:
            glow_color = QtGui.QColor(colors['glow'])
            glow_color.setAlphaF(0.3 * self._opacity)

            glow_gradient = QtGui.QRadialGradient(0, 0, 450)
            glow_gradient.setColorAt(0, glow_color)
            glow_gradient.setColorAt(1, QtCore.Qt.GlobalColor.transparent)

            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(glow_gradient)
            painter.drawEllipse(-450, -450, 900, 900)


class LabeledIndicator(QtWidgets.QWidget):
    """
    Status indicator with label.
    """

    state_changed = pyqtSignal(ConnectedStateEnum)

    def __init__(self, target_name: str,
                 parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._name = target_name
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Initialize the user interface."""
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create indicator
        self._indicator = StatusIndicator()
        layout.addWidget(self._indicator)

        # Create label with modern styling
        self._label = QtWidgets.QLabel(f"<b>{self._name}</b>")
        self._label.setStyleSheet("""
            QLabel {
                font-weight: 600;
                font-size: 11pt;
            }
        """)
        layout.addWidget(self._label)

        # Add stretch to push everything left
        layout.addStretch()

        # Set widget properties
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                           QtWidgets.QSizePolicy.Policy.Fixed)

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        self._indicator.state_changed.connect(self.state_changed.emit)

    @property
    def name(self) -> str:
        """Get the indicator name."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        """Set the indicator name."""
        self._name = value
        self._label.setText(f"<b>{value}</b>")

    @property
    def status(self) -> ConnectedStateEnum:
        """Get the current status."""
        return self._indicator.state

    @status.setter
    def status(self, state: ConnectedStateEnum) -> None:
        """Set the current status."""
        self._indicator.state = state

    def set_animation_enabled(self, enabled: bool) -> None:
        """Enable or disable animations."""
        self._indicator.set_animation_enabled(enabled)

    def set_pulse_enabled(self, enabled: bool) -> None:
        """Enable or disable pulse animation."""
        self._indicator.set_pulse_enabled(enabled)

    def set_color_scheme(self, state: ConnectedStateEnum,
                         primary: str, secondary: str, glow: str) -> None:
        """Customize colors for a specific state."""
        self._indicator.set_color_scheme(state, primary, secondary, glow)
