import inspect
from typing import Any

from PyQt6.QtWidgets import QWidget, QDoubleSpinBox

from qtgui.form.input.base import BaseInputWidget, ValidationResult


class FloatInputWidget(BaseInputWidget):
    """Widget for float input with validation."""

    def __init__(self,
                 param_name: str,
                 type_info: Any,
                 min_val: float = float('-inf'),
                 max_val: float = float('inf'),
                 decimals: int = 2,
                 parent: QWidget = None
                 ) -> None:
        self.min_val = min_val
        self.max_val = max_val
        self.decimals = decimals
        super().__init__(param_name, type_info, parent)

    def _build_widget(self) -> None:
        # TODO: consider ScientificLineEdit instead
        self._widget = QDoubleSpinBox(self.parent)
        self._widget.setMinimum(self.min_val)
        self._widget.setMaximum(self.max_val)
        self._widget.setDecimals(self.decimals)

        if self.type_info.default_value != inspect.Parameter.empty:
            self._widget.setValue(float(self.type_info.default_value))

    def get_value(self) -> float:
        return self._widget.value()

    def set_value(self, value: float) -> None:
        self._widget.setValue(value)

    def validate(self) -> ValidationResult:
        value = self.get_value()
        if self.min_val <= value <= self.max_val:
            return ValidationResult(True, value)
        return ValidationResult(
            False, None,
            f"Value must be between {self.min_val} and {self.max_val}"
        )
