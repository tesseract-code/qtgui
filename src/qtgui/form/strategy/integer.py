from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.form.input.base import BaseInputWidget
from qtgui.form.input.integer import IntegerInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy


class IntegerWidgetStrategy(WidgetCreationStrategy):
    """Strategy for creating integer input widget."""

    def can_handle(self, type_info: Any) -> bool:
        return type_info.base_type == int

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        return IntegerInputWidget(param_name, type_info, parent=parent)
