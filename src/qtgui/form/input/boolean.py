import inspect

from qtgui.form.input.base import BaseInputWidget, ValidationResult
from qtgui.switch import Switch


class BooleanInputWidget(BaseInputWidget):
    """Widget for boolean input."""

    def _build_widget(self) -> None:
        self._widget = Switch(self.parent, thumb_radius=11, track_radius=10)
        if self.type_info.default_value != inspect.Parameter.empty:
            self._widget.setChecked(bool(self.type_info.default_value))

    def get_value(self) -> bool:
        return self._widget.isChecked()

    def set_value(self, value: bool) -> None:
        self._widget.setChecked(value)

    def validate(self) -> ValidationResult:
        return ValidationResult(True, self.get_value())
