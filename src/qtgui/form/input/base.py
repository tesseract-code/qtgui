import inspect
from abc import ABC, abstractmethod
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QDoubleSpinBox,
    QSizePolicy,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox
)

class ValidationResult:
    """Result of input validation."""

    def __init__(self, is_valid: bool, value: Any = None, error: str = ""):
        self.is_valid = is_valid
        self.value = value
        self.error = error

class BaseInputWidget(ABC):
    """
    Abstract base class for all input widget.

    Defines the interface that all concrete input widget must implement.
    """

    def __init__(self, param_name: str, type_info: Any, parent: QWidget = None):
        """
        Initialize the input widget.

        Args:
            param_name: Name of the parameter this widget represents
            type_info: TypeInfo object from the SignatureMapper
            parent: Parent QWidget
        """
        self.param_name = param_name
        self.type_info = type_info
        self.parent = parent
        self._widget = None
        self._build_widget()

    @abstractmethod
    def _build_widget(self) -> None:
        """Build the actual Qt widget."""
        pass

    @abstractmethod
    def get_value(self) -> Any:
        """Get the current value from the widget."""
        pass

    @abstractmethod
    def set_value(self, value: Any) -> None:
        """Set the value in the widget."""
        pass

    @abstractmethod
    def validate(self) -> ValidationResult:
        """Validate the current input."""
        pass

    def get_widget(self) -> QWidget:
        """Get the underlying Qt widget."""
        frame = QFrame()

        layout = QHBoxLayout(frame)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(self._widget)

        if isinstance(self._widget, QDoubleSpinBox):
            self._widget.setSizePolicy(QSizePolicy(
                QSizePolicy.Policy.MinimumExpanding,
                QSizePolicy.Policy.Preferred))
        if isinstance(self._widget, (QLabel, QLineEdit, QDoubleSpinBox)):
            self._widget.setAlignment(Qt.AlignmentFlag.AlignRight)

        if not isinstance(self._widget, (QDoubleSpinBox, QComboBox, QSpinBox)):
            self._widget.setStyleSheet("""
                background: transparent;
                border: none;
                padding: 0px;
            """)
        else:
            edit = self._widget.lineEdit()

            if edit:
                edit.setStyleSheet("border: none; background: transparent;")
                edit.setAlignment(Qt.AlignmentFlag.AlignRight)
            else:
                widget = self._widget
                widget.setEditable(True)
                edit = widget.lineEdit()
                edit.setAlignment(Qt.AlignmentFlag.AlignRight)

        return frame

    def cast_to_type(self, value: Any) -> Any:
        """
        Cast the value to the expected type.

        Args:
            value: Raw value from the widget

        Returns:
            Value cast to the correct type
        """
        target_type = self.type_info.base_type
        
        try:
            # Handle None/Optional
            if value is None or value == "":
                if self.type_info.is_optional:
                    return None
                elif self.type_info.default_value != inspect.Parameter.empty:
                    return self.type_info.default_value

            # Primitive type casting
            if target_type in (int, float, str, bool):
                return target_type(value)

            # Try direct casting
            return target_type(value)

        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Cannot cast '{value}' to {target_type.__name__}: {e}")
