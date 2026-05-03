from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import (
    QLabel,
)


class OutlineLabel(QLabel):
    """
    Custom QLabel with outline (border) support and configurable properties.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.outline_color = QColor(255, 0, 0)  # Default red
        self.outline_width = 2
        self.antialiasing = True
        self.background_opacity = 0.0  # Transparent by default
        self.background_color = QColor(0, 0, 0)  # Black background

    def set_outline_color(self, color: QColor):
        """Set the outline/border color for the text."""
        self.outline_color = color
        self.update()

    def set_outline_width(self, width: int):
        """Set the outline/border width in pixels."""
        self.outline_width = max(1, width)
        self.update()

    def set_antialiasing(self, enabled: bool):
        """Enable or disable text antialiasing."""
        self.antialiasing = enabled
        self.update()

    def set_background_opacity(self, opacity: float):
        """
        Set background opacity from 0.0 (transparent) to 1.0 (opaque).
        """
        self.background_opacity = max(0.0, min(1.0, opacity))
        self.update()

    def set_background_color(self, color: QColor):
        """Set the background color (will be affected by opacity)."""
        self.background_color = color
        self.update()

    def paintEvent(self, event):
        """Custom paint event to draw outlined text and background."""
        painter = QPainter(self)

        # Enable antialiasing if requested
        if self.antialiasing:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Get widget dimensions
        rect = self.rect()

        # Draw background with opacity
        if self.background_opacity > 0:
            bg_color = QColor(self.background_color)
            bg_color.setAlphaF(self.background_opacity)
            painter.fillRect(rect, bg_color)

        # Get text content
        text = self.text()
        if not text:
            return

        # Configure font
        font = self.font()
        painter.setFont(font)

        # Configure text color from palette
        text_color = self.palette().color(self.foregroundRole())

        # Calculate text position based on alignment
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()

        # Calculate position based on alignment
        alignment = self.alignment()

        if alignment & Qt.AlignmentFlag.AlignLeft:
            x = 0
        elif alignment & Qt.AlignmentFlag.AlignRight:
            x = rect.width() - text_width
        else:  # Center (default)
            x = (rect.width() - text_width) // 2

        if alignment & Qt.AlignmentFlag.AlignTop:
            y = text_height
        elif alignment & Qt.AlignmentFlag.AlignBottom:
            y = rect.height()
        else:  # Center (default)
            y = (rect.height() + text_height) // 2 - metrics.descent()

        # Draw outline if width > 0
        if self.outline_width > 0:
            pen = QPen(self.outline_color)
            pen.setWidth(self.outline_width)
            painter.setPen(pen)

            # Draw text multiple times with offsets to create outline
            offsets = [
                (-self.outline_width, -self.outline_width),
                (-self.outline_width, 0),
                (-self.outline_width, self.outline_width),
                (0, -self.outline_width),
                (0, self.outline_width),
                (self.outline_width, -self.outline_width),
                (self.outline_width, 0),
                (self.outline_width, self.outline_width),
            ]

            for dx, dy in offsets:
                painter.drawText(x + dx, y + dy, text)

        # Draw main text
        painter.setPen(QPen(text_color))
        painter.drawText(x, y, text)
