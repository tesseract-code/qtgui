import inspect
from typing import Any

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from qtgui.color_picker import ColorPickerButton, to_qcolor
from qtgui.form.input.base import BaseInputWidget, ValidationResult


class ColorInputWidget(BaseInputWidget):
    """Widget for color input using the ColorPickerButton"""

    def __init__(self, param_name: str, type_info: Any, parent: QWidget = None):
        self._treat_as_color = True
        self._color_picker = None
        # Widget is built, so order here matters or the reference to
        # _color_picker would be overwritten
        super().__init__(param_name, type_info, parent)

    def _build_widget(self) -> None:
        """Build the color input widget using ColorPickerButton"""
        container = QWidget(self.parent)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # Use the ColorPickerButton with the parameter name as label
        self._color_picker = ColorPickerButton(
            label=self.param_name,
            initial_color=self._get_initial_color(),
            parent=container
        )

        layout.addWidget(self._color_picker)
        self._widget = container

    def _get_initial_color(self) -> QColor:
        """Get initial color from default value or use default"""
        if (hasattr(self.type_info, 'default_value') and
                self.type_info.default_value != inspect.Parameter.empty):
            return to_qcolor(self.type_info.default_value)
        return QColor(130, 53, 220)  # Default purple

    def get_value(self) -> Any:
        """Get the current color value in the appropriate type"""
        if self._color_picker:
            color = self._color_picker.get_color()
            # Return in the format expected by the original type annotation
            if (hasattr(self.type_info, 'base_type') and
                    self.type_info.base_type == str):
                return color.name().upper()  # Return as hex string
            else:
                return color  # Return as QColor

        return self._get_initial_color()

    def set_value(self, value: Any) -> None:
        """Set the current color from any supported format"""
        if self._color_picker:
            self._color_picker.set_color(value)

    def validate(self) -> ValidationResult:
        """Validate the color input"""
        value = self.get_value()
        if isinstance(value, QColor) and value.isValid():
            return ValidationResult(True, value)
        elif isinstance(value, str) and QColor(value).isValid():
            return ValidationResult(True, value)
        else:
            return ValidationResult(False, None, "Invalid color value")
