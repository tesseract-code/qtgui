import logging
from typing import Optional

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QIcon, QPixmap

from qtgui.log.constants import LOG_LEVEL_ICONS, LOG_LEVEL_COLORS, BADGE_HEIGHT
from qtgui.pixmap import colorize_pixmap


class LogLevelBadge(QtWidgets.QFrame):
    """A colored badge widget displaying log level counts."""

    clicked = QtCore.pyqtSignal()

    def __init__(
            self,
            level: int,
            parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        """
        Initialize the badge.

        Args:
            level: The logging level (logging.DEBUG, logging.INFO, etc.)
            parent: Parent widget
        """
        super().__init__(parent)

        self._level = level

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        self.setLayout(layout)

        # Icon
        icon_path = LOG_LEVEL_ICONS.get(level)
        if icon_path:
            icon_label = QtWidgets.QToolButton()
            # icon_label.setMinimumHeight(32)
            icon_label.setStyleSheet("background: transparent; border: none;")
            icon_label.setCheckable(False)
            # icon_label.setEnabled(False)
            icon_label.setIcon(
            QIcon(
                colorize_pixmap(
                    QPixmap(icon_path),
                    color=QColor("white"))
            ))
            layout.addWidget(icon_label)

        # Level name from logging module
        level_name = logging.getLevelName(level)
        name_label = QtWidgets.QLabel(f"{level_name}:")
        name_label.setStyleSheet("color: white;")
        layout.addWidget(name_label)

        # Count
        self._count_label = QtWidgets.QLabel("0")
        self._count_label.setStyleSheet("font-weight: bold; color: white;")
        layout.addWidget(self._count_label)

        # Style the badge
        color = QColor(LOG_LEVEL_COLORS.get(level, "none")).darker(110).name()
        self.setStyleSheet(f"""background-color: {color};
                border-radius: 4px;
        """)
        self.setMaximumHeight(BADGE_HEIGHT)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def set_count(self, count: int) -> None:
        """
        Update the displayed count.

        Args:
            count: The count to display
        """
        self._count_label.setText(str(count))

    def get_level(self) -> int:
        """
        Get the log level associated with this badge.

        Returns:
            The logging level constant
        """
        return self._level

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Handle mouse press events."""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
