from abc import ABC, abstractmethod
from typing import Any

from PyQt6.QtWidgets import QWidget

from qtgui.form.input.base import BaseInputWidget


class WidgetCreationStrategy(ABC):
    """Abstract strategy for creating widget based on type information."""

    @abstractmethod
    def can_handle(self, type_info: Any) -> bool:
        """Check if this strategy can handle the given type."""
        pass

    @abstractmethod
    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        """Create the appropriate widget."""
        pass
