from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.form.input.base import BaseInputWidget
from qtgui.form.input.float import FloatInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy


class FloatWidgetStrategy(WidgetCreationStrategy):
    """Strategy for creating float input widget."""

    def can_handle(self, type_info: Any) -> bool:
        return type_info.base_type == float

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        return FloatInputWidget(param_name, type_info, parent=parent)
