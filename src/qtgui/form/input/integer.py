import inspect
from typing import Any

from PyQt6.QtWidgets import QWidget, QSpinBox

from qtgui.form.input.base import BaseInputWidget, ValidationResult


class IntegerInputWidget(BaseInputWidget):
    """Widget for integer input with validation."""

    def __init__(self, param_name: str, type_info: Any,
                 min_val: int = -2147483648, max_val: int = 2147483647,
                 parent: QWidget = None):
        self.min_val = min_val
        self.max_val = max_val
        super().__init__(param_name, type_info, parent)

    def _build_widget(self) -> None:
        self._widget = QSpinBox(self.parent)
        self._widget.setMinimum(self.min_val)
        self._widget.setMaximum(self.max_val)

        # Set default value if available
        if self.type_info.default_value != inspect.Parameter.empty:
            self._widget.setValue(int(self.type_info.default_value))

    def get_value(self) -> int:
        return self._widget.value()

    def set_value(self, value: int) -> None:
        self._widget.setValue(value)

    def validate(self) -> ValidationResult:
        value = self.get_value()
        if self.min_val <= value <= self.max_val:
            return ValidationResult(True, value)
        return ValidationResult(
            False, None,
            f"Value must be between {self.min_val} and {self.max_val}"
        )
