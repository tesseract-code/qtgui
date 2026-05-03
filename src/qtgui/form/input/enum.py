import inspect
from enum import Enum
from typing import Any, Type

from PyQt6.QtWidgets import QWidget, QComboBox

from qtgui.form.input.base import BaseInputWidget, ValidationResult


class EnumInputWidget(BaseInputWidget):
    """Widget for enum selection."""

    def __init__(self, param_name: str, type_info: Any,
                 enum_class: Type[Enum], parent: QWidget = None):
        self.enum_class = enum_class
        super().__init__(param_name, type_info, parent)

    def _build_widget(self) -> None:
        self._widget = QComboBox(self.parent)

        # Populate with enum values
        for member in self.enum_class:
            self._widget.addItem(member.name, member)

        # Set default if available
        if self.type_info.default_value != inspect.Parameter.empty:
            index = self._widget.findData(self.type_info.default_value)
            if index >= 0:
                self._widget.setCurrentIndex(index)

    def get_value(self) -> Enum:
        return self._widget.currentData()

    def set_value(self, value: Enum) -> None:
        index = self._widget.findData(value)
        if index >= 0:
            self._widget.setCurrentIndex(index)

    def validate(self) -> ValidationResult:
        value = self.get_value()
        if isinstance(value, self.enum_class):
            return ValidationResult(True, value)
        return ValidationResult(False, None, "Invalid enum value")
