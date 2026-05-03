import inspect
from typing import Any

from PyQt6.QtWidgets import QWidget, QTextEdit, QLineEdit

from qtgui.form.input.base import BaseInputWidget, ValidationResult


class StringInputWidget(BaseInputWidget):
    """Widget for string input."""

    def __init__(self, param_name: str, type_info: Any,
                 multiline: bool = False, parent: QWidget = None):
        self.multiline = multiline
        super().__init__(param_name, type_info, parent)

    def _build_widget(self) -> None:
        if self.multiline:
            self._widget = QTextEdit(self.parent)
            if self.type_info.default_value != inspect.Parameter.empty:
                self._widget.setPlainText(str(self.type_info.default_value))
        else:
            self._widget = QLineEdit(self.parent)
            if self.type_info.default_value != inspect.Parameter.empty:
                if self.type_info.default_value:
                    self._widget.setText(str(self.type_info.default_value))
                else:
                    self._widget.setText("---")

    def get_value(self) -> str:
        text = (self._widget.toPlainText()
                if self.multiline
                else self._widget.text())

        if text == "---":
            return ""
        return text

    def set_value(self, value: str) -> None:
        if self.multiline:
            self._widget.setPlainText(str(value))
        else:
            self._widget.setText(str(value))

    def validate(self) -> ValidationResult:
        value = self.get_value()
        return ValidationResult(True, value)
