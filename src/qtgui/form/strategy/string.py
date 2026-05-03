from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.form.input.base import BaseInputWidget
from qtgui.form.input.string import StringInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy


class StringWidgetStrategy(WidgetCreationStrategy):
    """Strategy for creating string input widget."""

    def can_handle(self, type_info: Any) -> bool:
        return type_info.base_type == str

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        multiline = 'multiline' in type_info.metadata
        return StringInputWidget(param_name, type_info,
                                 multiline=multiline, parent=parent)
