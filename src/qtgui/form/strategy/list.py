from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.form.input.array import ArrayInputWidget
from qtgui.form.input.base import BaseInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy


class ListWidgetStrategy(WidgetCreationStrategy):
    """Strategy for creating list/array input widget."""

    def can_handle(self, type_info: Any) -> bool:
        return type_info.base_type in (list, tuple)

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        # Determine element type from type args
        element_type = float
        if type_info.type_args:
            element_type = type_info.type_args[0]

        # Get shape from metadata if available
        shape = type_info._frame_stats.get('shape', (3,))

        return ArrayInputWidget(param_name, type_info, shape=shape,
                                element_type=element_type, parent=parent)
