import inspect
from enum import Enum
from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.form.input.base import BaseInputWidget
from qtgui.form.input.enum import EnumInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy


class EnumWidgetStrategy(WidgetCreationStrategy):
    """Strategy for creating enum input widget."""

    def can_handle(self, type_info: Any) -> bool:
        return (inspect.isclass(type_info.base_type) and
                issubclass(type_info.base_type, Enum))

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        return EnumInputWidget(param_name, type_info,
                               type_info.base_type, parent=parent)
