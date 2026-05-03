from PIL.ImageQt import QPixmap
from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDoubleValidator, QColor, QIcon
from PyQt6.QtWidgets import QLineEdit

from qtgui.pixmap import colorize_pixmap


class ScientificLineEdit(QLineEdit):
    """Line edit that formats numbers in scientific notation when appropriate."""

    valueChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._block_updates = False  # Prevent recursion during editingFinished
        self._current_value = 0.0

        # StandardNotation accepts both plain decimals and scientific notation
        validator = QDoubleValidator()
        validator.setDecimals(3)
        validator.setNotation(
            QDoubleValidator.Notation.StandardNotation)  # Fix #3
        self.setValidator(validator)

        self.editingFinished.connect(self._on_editing_finished)
        self.textChanged.connect(
            self._adjust_width)  # Fix #1: textChanged, not validator().changed

    @pyqtSlot()
    def _on_editing_finished(self):
        """Handle editing finished - format and emit signal."""
        if self._block_updates:  # Skip if we're currently formatting
            return

        current_text = self.text().strip()
        if current_text:
            try:
                value = float(current_text)
                self._current_value = value

                formatted_text = self._format_value(
                    value)  # Fix #5: extracted helper

                self._block_updates = True
                try:
                    self.setText(formatted_text)
                finally:
                    self._block_updates = False

                self.valueChanged.emit(value)

            except ValueError:
                # Invalid input - revert to last valid value
                self.setValue(self._current_value)

    def _format_value(self, value: float) -> str:
        """Format a float for display, using scientific notation for large/small values."""  # Fix #5
        if abs(value) >= 1000.0 or (abs(value) < 0.001 and value != 0):
            return f"{value:.3e}"
        return f"{value:.3f}"

    def _adjust_width(self, text: str):
        """Adjust widget width to fit text content."""
        width = self.fontMetrics().boundingRect(text).width() + 30
        sh = self.sizeHint()
        self.setMaximumWidth(max(sh.width(), width))  # Fix #2: max, not min

    def value(self) -> float:  # Fix #7: plain method, not @property
        """Get the current value as a float."""
        return self._current_value

    def setValue(self, value: float):
        """Set value with intelligent formatting (Qt naming convention)."""  # Fix #7
        self._current_value = value

        self._block_updates = True
        try:
            text = self._format_value(value)  # Fix #5: use shared helper
            self.setText(text)
        except (ValueError, TypeError):
            self.setText("0.0")
        finally:
            self._block_updates = False

        self.valueChanged.emit(value)  # Fix #4: emit after programmatic set


class SearchLineEdit(QLineEdit):
    def __init__(self, placeholder: str = "Search...", parent=None):
        super().__init__(parent=parent)
        self.addAction(
            QIcon(
                colorize_pixmap(QPixmap(
                    "line-icons:search-line.svg"
                ),
                    QColor(
                        self.palette().highlight().color()
                    )
                )
            ),
            QLineEdit.ActionPosition.LeadingPosition)
        self.setPlaceholderText(placeholder)
        self.setStyleSheet("border-radius: 4px;")
        self.setClearButtonEnabled(True)
