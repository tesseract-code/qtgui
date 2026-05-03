from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.form.input.base import BaseInputWidget
from qtgui.form.input.string import StringInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy


class FallbackWidgetStrategy(WidgetCreationStrategy):
    """Fallback strategy for unknown types."""

    def can_handle(self, type_info: Any) -> bool:
        return True  # Always can handle as last resort

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        # Default to string input for unknown types
        return StringInputWidget(param_name, type_info, parent=parent)
