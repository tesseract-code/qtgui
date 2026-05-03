from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.color_picker import Color
from qtgui.form.input.base import BaseInputWidget
from qtgui.form.input.color import ColorInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy


class ColorWidgetStrategy(WidgetCreationStrategy):
    """Strategy for color input widget - specifically handles Color type"""

    def __init__(self):
        # Store a reference to the actual Color type for comparison
        self.color_type = Color

    def can_handle(self, type_info: Any) -> bool:
        """Handle the specific Color type through multiple detection methods"""
        # Method 1: Check if original_type is our Color type
        if (hasattr(type_info, 'original_type') and
                type_info.original_type == self.color_type):
            return True

        # Method 2: Check annotation string for Color type
        if (hasattr(type_info, 'annotation_string') and
                type_info.annotation_string == 'Color'):
            return True

        # Method 3: Check if it's explicitly marked as a color in metadata
        if (hasattr(type_info, 'metadata') and
                type_info.metadata.get('is_color', False)):
            return True

        # Method 4: Check parameter name with high confidence
        if hasattr(type_info, 'param_name'):
            param_name_lower = type_info.param_name.lower()
            # Very specific color terms only
            high_confidence_terms = [
                'color', 'colour', 'fillcolor', 'linecolor', 'bordercolor',
                'backgroundcolor', 'foregroundcolor', 'textcolor', 'pen_color'
            ]
            if any(term == param_name_lower for term in high_confidence_terms):
                return True
            # Also check if parameter name ends with 'color'
            if param_name_lower.endswith('color') or param_name_lower.endswith(
                    'colour'):
                return True

        return False

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        widget = ColorInputWidget(param_name, type_info)
        return widget
