import inspect
from typing import Any, List

from PyQt6.QtWidgets import QWidget, QComboBox

from qtgui.form.input.base import BaseInputWidget
from qtgui.form.factory import ValidationResult


class ChoiceInputWidget(BaseInputWidget):
    """Widget for selecting from a list of choices."""

    def __init__(self, param_name: str, type_info: Any,
                 choices: List[Any], parent: QWidget = None):
        self.choices = choices
        super().__init__(param_name, type_info, parent)

    def _build_widget(self) -> None:
        self._widget = QComboBox(self.parent)
        for choice in self.choices:
            self._widget.addItem(str(choice), choice)

        if self.type_info.default_value != inspect.Parameter.empty:
            index = self._widget.findData(self.type_info.default_value)
            if index >= 0:
                self._widget.setCurrentIndex(index)

    def get_value(self) -> Any:
        return self._widget.currentData()

    def set_value(self, value: Any) -> None:
        index = self._widget.findData(value)
        if index >= 0:
            self._widget.setCurrentIndex(index)

    def validate(self) -> ValidationResult:
        value = self.get_value()
        if value in self.choices:
            return ValidationResult(True, value)
        return ValidationResult(False, None, "Value not in allowed choices")
