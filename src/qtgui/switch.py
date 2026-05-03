import sys
from typing import Dict

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from PyQt6 import QtWidgets, QtCore, QtGui
from typing import Final


class Switch(QtWidgets.QAbstractButton):
    """
    MacOS-style animated toggle switch.

    A clean, modern switch widget that mimics the appearance and behavior
    of native MacOS toggle switches.
    """

    # Animation constants
    _ANIMATION_DURATION: Final[int] = 200
    _ANIMATION_CURVE: Final[
        QtCore.QEasingCurve.Type] = QtCore.QEasingCurve.Type.InOutCubic

    # Color constants
    _TRACK_ON_COLOR: Final[QtGui.QColor] = QtGui.QColor('#007AFF')
    _TRACK_OFF_COLOR: Final[QtGui.QColor] = QtGui.QColor('#E5E5EA')
    _TRACK_DISABLED_COLOR: Final[QtGui.QColor] = QtGui.QColor('#D1D1D6')
    _TRACK_BORDER_ON_COLOR: Final[QtGui.QColor] = QtGui.QColor('#D1D1D6')
    _TRACK_BORDER_OFF_COLOR: Final[QtGui.QColor] = QtGui.QColor('#D1D1D6')
    _TRACK_BORDER_DISABLED_COLOR: Final[QtGui.QColor] = QtGui.QColor('#C7C7CC')
    _THUMB_COLOR: Final[QtGui.QColor] = QtGui.QColor('#FFFFFF')
    _THUMB_DISABLED_COLOR: Final[QtGui.QColor] = QtGui.QColor('#F2F2F7')
    _SHADOW_COLOR: Final[QtGui.QColor] = QtGui.QColor(0, 0, 0, 30)
    _THUMB_BORDER_COLOR: Final[QtGui.QColor] = QtGui.QColor(0, 0, 0, 20)

    def __init__(
            self,
            parent: QtWidgets.QWidget = None,
            track_radius: int = 10,
            thumb_radius: int = 8
    ) -> None:
        super().__init__(parent)

        # Ensure thumb is smaller than track for proper MacOS appearance
        self._track_radius: int = track_radius
        self._thumb_radius: int = min(thumb_radius, track_radius - 2)
        self._track_margin: int = 2
        self._track_inset: int = 1
        self._shadow_offset: int = 1

        # Calculate positioning
        self._track_height: int = 2 * self._track_radius
        self._track_width: int = 4 * self._track_radius
        self._thumb_center_y: int = self._track_radius + self._track_margin

        # Thumb positioning (centered vertically in track)
        self._thumb_y: int = self._thumb_center_y - self._thumb_radius

        # Thumb X positions (with proper padding from edges)
        self._thumb_padding: int = self._track_radius - self._thumb_radius
        self._thumb_x_off: int = self._track_margin + self._thumb_padding
        self._thumb_x_on: int = (
                self._track_margin + self._track_width - self._thumb_padding - 2 * self._thumb_radius
        )

        # Current thumb position
        self._thumb_x: int = self._thumb_x_off

        # Pre-compute geometry for O(1) lookup
        self._track_rect: QtCore.QRectF = QtCore.QRectF(
            self._track_margin,
            self._track_margin,
            self._track_width,
            self._track_height
        )

        self._track_fill_rect: QtCore.QRectF = QtCore.QRectF(
            self._track_margin + self._track_inset,
            self._track_margin + self._track_inset,
            self._track_width - 2 * self._track_inset,
            self._track_height - 2 * self._track_inset
        )

        # Configure widget
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed
        )

    @QtCore.pyqtProperty(int)
    def thumb_x(self) -> int:
        """Current X position of the thumb."""
        return self._thumb_x

    @thumb_x.setter
    def thumb_x(self, value: int) -> None:
        self._thumb_x = value
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        """Return the preferred size for the switch."""
        return QtCore.QSize(
            self._track_width + 2 * self._track_margin,
            self._track_height + 2 * self._track_margin
        )

    def setChecked(self, checked: bool) -> None:
        """Set the checked state without animation."""
        super().setChecked(checked)
        self._thumb_x = self._thumb_x_on if checked else self._thumb_x_off
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint the switch."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # O(1) color lookup based on state
        is_enabled = self.isEnabled()
        is_checked = self.isChecked()

        if is_enabled:
            track_brush = self._TRACK_ON_COLOR if is_checked else self._TRACK_OFF_COLOR
            track_border = self._TRACK_BORDER_ON_COLOR if is_checked else self._TRACK_BORDER_OFF_COLOR
            thumb_brush = self._THUMB_COLOR
        else:
            track_brush = self._TRACK_DISABLED_COLOR
            track_border = self._TRACK_BORDER_DISABLED_COLOR
            thumb_brush = self._THUMB_DISABLED_COLOR

        # Draw track border
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(track_border)
        painter.setOpacity(1.0)
        painter.drawRoundedRect(
            self._track_rect,
            self._track_radius,
            self._track_radius
        )

        # Draw track fill
        painter.setBrush(track_brush)
        painter.drawRoundedRect(
            self._track_fill_rect,
            self._track_radius - self._track_inset,
            self._track_radius - self._track_inset
        )

        # Draw thumb shadow
        painter.setBrush(self._SHADOW_COLOR)
        painter.setOpacity(0.3)
        painter.drawEllipse(
            self._thumb_x + self._shadow_offset,
            self._thumb_y + self._shadow_offset,
            2 * self._thumb_radius,
            2 * self._thumb_radius
        )

        # Draw thumb
        painter.setPen(QtGui.QPen(self._THUMB_BORDER_COLOR, 0.5))
        painter.setBrush(thumb_brush)
        painter.setOpacity(1.0)
        painter.drawEllipse(
            self._thumb_x,
            self._thumb_y,
            2 * self._thumb_radius,
            2 * self._thumb_radius
        )

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Handle mouse release with smooth animation."""
        super().mouseReleaseEvent(event)

        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            # Animate thumb position
            animation = QtCore.QPropertyAnimation(self, b'thumb_x', self)
            animation.setDuration(self._ANIMATION_DURATION)
            animation.setEasingCurve(self._ANIMATION_CURVE)
            animation.setStartValue(self._thumb_x)
            animation.setEndValue(
                self._thumb_x_on if self.isChecked() else self._thumb_x_off
            )
            animation.start()

    def hitButton(self, pos: QtCore.QPoint) -> bool:
        """Return True if pos is within the switch's clickable area."""
        return self.contentsRect().contains(pos)


def get_state_switch(state: bool = False):
    switch = Switch()
    switch.setChecked(state)
    switch.track_color = {
        True: QtGui.QBrush(QtGui.QColor('lightGreen')),
        False: QtGui.QBrush(QtGui.QColor('red'))
    }
    switch.thumb_color = {
        True: QtGui.QBrush(QtGui.QColor('darkGreen')),
        # darkRed does not have good contrast
        False: QtGui.QBrush(QtGui.QColor(88, 0, 1))
    }
    return switch


class ToggleSwitchDemo(QtWidgets.QWidget):
    """Demo application showing different toggle switch configurations"""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Modern PyQt6 Toggle Switch Demo')
        self.setFixedSize(400, 300)

        # Center the window
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        # x = (screen.width() - self.width()) // 2
        # y = (screen.height() - self.height()) // 2
        # self.setGeometry(x, y, self.width(), self.height())

        layout = QtWidgets.QVBoxLayout(self)
        # layout.setSpacing(20)
        # layout.setContentsMargins(30, 30, 30, 30)

        # Title
        title = QtWidgets.QLabel('Modern Toggle Switch Demo')
        # title.setStyleSheet(
        #     'font-size: 18px; font-weight: bold; margin-bottom: 10px;')
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)

        # Standard toggle switch
        self.add_switch_row(layout, 'Standard Toggle:', Switch())

        # Large toggle switch
        large_switch = Switch(track_radius=12, thumb_radius=16)
        self.add_switch_row(layout, 'Large Toggle:', large_switch)

        # Icon toggle switch (small thumb)
        icon_switch = Switch(track_radius=14, thumb_radius=8)
        self.add_switch_row(layout, 'With Icons:', icon_switch)

        # Fast animation
        fast_switch = Switch()
        self.add_switch_row(layout, 'Fast Animation:', fast_switch)

        # Status label
        self.status_label = QtWidgets.QLabel(
            'Toggle switches to see state changes')
        # self.status_label.setStyleSheet(
        #     'color: #666; font-style: italic; margin-top: 20px;')
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        layout.addStretch()

        # Set modern styling
        # self.setStyleSheet('''
        #     QWidget {
        #         background-color: #FAFAFA;
        #         font-family: 'Segoe UI', Arial, sans-serif;
        #     }
        # ''')

    def add_switch_row(self, layout: QtWidgets.QVBoxLayout, label_text: str,
                       switch: Switch):
        """Add a labeled switch to the layout"""
        row_layout = QtWidgets.QHBoxLayout()

        label = QtWidgets.QLabel(label_text)
        label.setFixedWidth(150)
        label.setStyleSheet('font-size: 14px;')

        row_layout.addWidget(label)
        row_layout.addWidget(switch)
        row_layout.addStretch()

        # Connect to status update
        switch.toggled.connect(lambda checked, text=label_text:
                               self.update_status(text, checked))

        layout.addLayout(row_layout)

    def update_status(self, switch_name: str, state: bool):
        """Update status label when switch changes"""
        state_text = 'ON' if state else 'OFF'
        self.status_label.setText(f'{switch_name} is now {state_text}')


def main():
    """Main application entry point"""
    app = QtWidgets.QApplication(sys.argv)

    # Set application properties
    app.setApplicationName('Toggle Switch Demo')
    app.setApplicationVersion('1.0')

    # Create and show demo window
    demo = ToggleSwitchDemo()
    demo.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()