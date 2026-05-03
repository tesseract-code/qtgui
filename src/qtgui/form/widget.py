import inspect
from dataclasses import dataclass, is_dataclass, fields
from typing import Callable, Dict, List, Any, Optional, Tuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox
)

from qtgui.form.factory import WidgetFactory, unwrap_optional
from qtgui.form.group import FormGroup
from qtgui.form.input.base import BaseInputWidget


class DynamicFormWidget(QFrame):
    """
    Dynamic form widget that generates input fields based on callable signature.
    Supports grouping of related parameters.
    """

    values_changed = pyqtSignal()

    def __init__(self, callable_obj: Callable, signature_mapper=None,
                 group_mapping: Dict[str, List[str]] = None,
                 parent: QWidget = None):
        """
        Initialize the dynamic form widget.

        Args:
            callable_obj: Function, class, or callable to create form for
            signature_mapper: SignatureMapper instance (created if not provided)
            group_mapping: Optional dict mapping group names to parameter lists
            parent: Parent widget
        """
        super().__init__(parent)

        self.callable_obj = callable_obj
        self.signature_mapper = signature_mapper
        if self.signature_mapper is None:
            from pycore.maptype import SignatureMapper  # Replace with actual
            # import
            self.signature_mapper = SignatureMapper()
        self.widget_factory = WidgetFactory()
        self.input_widgets: Dict[str, BaseInputWidget] = {}
        self.group_mapping = group_mapping

        # Set frame properties
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: transparent;")

        self._build_form()

    def _build_form(self) -> None:
        """Build the form layout with all parameter widget, grouped if specified."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Get parameter type information
        if self.signature_mapper:
            type_map = self.signature_mapper.map_callable_signature(
                self.callable_obj
            )
        else:
            type_map = {}

        # Get grouping information (now returns list of FormGroup objects)
        groups = self._get_parameter_groups(list(type_map.keys()))

        if groups:
            self._build_grouped_form(layout, type_map, groups)
        else:
            self._build_ungrouped_form(layout, type_map)

    def _get_parameter_groups(self, param_names: List[str]) -> List[FormGroup]:
        """Extract grouping information from the callable or use provided mapping."""
        # Priority 1: Use explicitly provided group mapping
        if self.group_mapping:
            return [FormGroup(name, None, params)
                    for name, params in self.group_mapping.items()]

        # Priority 2: Extract from form_group decorators
        if hasattr(self.callable_obj, '_form_groups'):
            form_groups = self.callable_obj._form_groups
            if form_groups:
                # Reverse to get source order
                reversed_groups = list(reversed(form_groups))

                return reversed_groups

        # Priority 3: Auto-detect groups based on parameter names
        auto_groups = self._auto_detect_groups(param_names)
        if auto_groups:
            return [FormGroup(name, None, params)
                    for name, params in auto_groups.items()]

        return []

    def _auto_detect_groups(self, param_names: List[str]) -> Dict[
        str, List[str]]:
        """Automatically detect groups based on parameter name patterns."""
        groups = {}
        general_params = []

        for param in param_names:
            general_params.append(param)

        if general_params:
            groups['General Settings'] = general_params

        return groups

    def _build_grouped_form(self, layout: QVBoxLayout, type_map: Dict,
                            groups: List[FormGroup]):
        """Build form with grouped parameters."""
        used_params = set()

        for group in groups:
            # Filter out parameters that don't exist in type_map
            valid_params = [p for p in group.parameters
                            if p in type_map and p not in ('self', 'cls')]
            if not valid_params:
                continue

            # Create group frame with description
            group_frame = self._create_group_frame(group.name,
                                                   group.description)
            group_layout = group_frame.layout()

            # Add parameters to group
            for i, param_name in enumerate(valid_params):
                type_info = type_map[param_name]
                param_widget = self._create_parameter_row(
                    param_name, type_info,
                    show_border=i < len(valid_params) - 1
                )
                group_layout.addWidget(param_widget)
                used_params.add(param_name)

            layout.addWidget(group_frame)

        # Handle any ungrouped parameters
        ungrouped_params = set(type_map.keys()) - used_params - {'self', 'cls'}
        if ungrouped_params:
            group_frame = self._create_group_frame("Other Settings", None)
            group_layout = group_frame.layout()

            ungrouped_list = list(ungrouped_params)
            for i, param_name in enumerate(ungrouped_list):
                type_info = type_map[param_name]
                param_widget = self._create_parameter_row(
                    param_name, type_info,
                    show_border=i < len(ungrouped_list) - 1
                )
                group_layout.addWidget(param_widget)

            layout.addWidget(group_frame)

        layout.addStretch()

    def _build_ungrouped_form(self, layout: QVBoxLayout, type_map: Dict):
        """Build form without grouping (original behavior)."""
        for param_name, type_info in type_map.items():
            if param_name in ('self', 'cls'):
                continue

            # Create entry frame
            entry_frame = QFrame()
            entry_frame.setObjectName("entryFrame")
            entry_frame.setFrameStyle(QFrame.Shape.NoFrame)
            entry_frame.setStyleSheet("""
                QFrame#entryFrame {
                    background-color: #f5f5f5;
                    border: 1px solid lightGray;
                    border-radius: 6px;
                }
            """)
            entry_frame.setFixedWidth(500)

            # Create horizontal layout for the entry
            entry_layout = QHBoxLayout(entry_frame)
            entry_layout.setSpacing(0)

            # Create label
            label_text = self._format_label(param_name, type_info)
            label = QLabel(label_text)
            label.setMinimumWidth(180)
            label.setWordWrap(True)
            entry_layout.addWidget(label)

            # Add stretch
            entry_layout.addStretch()

            # Create input widget
            input_widget = self.widget_factory.create_widget(
                param_name, type_info, self
            )
            self.input_widgets[param_name] = input_widget

            # Get the typed input widget and style it
            typed_input_widget = input_widget.get_widget()
            typed_input_widget.setParent(entry_frame)

            entry_layout.addWidget(typed_input_widget)
            typed_input_widget.setParent(entry_frame)

            layout.addWidget(entry_frame)

        layout.addStretch()

    def _format_label(self, param_name: str, type_info: Any) -> str:
        """Format a label for a parameter."""
        # Convert snake_case to Title Case
        label = param_name.replace('_', ' ').title()

        # Add asterisk for required parameters
        if (type_info.default_value == inspect.Parameter.empty and
                not type_info.is_optional):
            label += " *"

        return label

    def _create_group_frame(self, group_name: str,
                            description: Optional[str] = None) -> QFrame:
        """Create a frame for a group of parameters with optional description."""
        group_frame = QFrame()
        group_frame.setObjectName("groupFrame")
        group_frame.setFrameStyle(QFrame.Shape.NoFrame)
        group_frame.setStyleSheet("""
            QFrame#groupFrame {
                background-color: palette(light);
                border: 1px solid #e1e5e9;
                border-radius: 8px;
                margin: 0px;
            }
        """)
        group_frame.setMinimumWidth(500)

        layout = QVBoxLayout(group_frame)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create header container
        header_container = QWidget()
        header_container.setStyleSheet("""
            QWidget {
                background-color: #f8fafc;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border-bottom: 1px solid #e1e5e9;
            }
        """)
        header_layout = QVBoxLayout(header_container)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(4)

        # Add group title
        title = QLabel(group_name)
        title.setStyleSheet("""
            QLabel {
                font-weight: 600;
                font-size: 14px;
                color: #1a365d;
                background-color: transparent;
                border: none;
            }
        """)
        header_layout.addWidget(title)

        # Add description if provided
        if description:
            desc_label = QLabel(description)
            desc_label.setStyleSheet("""
                QLabel {
                    font-weight: 400;
                    font-size: 12px;
                    color: #64748b;
                    background-color: transparent;
                    border: none;
                }
            """)
            desc_label.setWordWrap(True)
            header_layout.addWidget(desc_label)

        layout.addWidget(header_container)

        return group_frame

    def _create_parameter_row(self, param_name: str, type_info: Any,
                              show_border: bool = True) -> QWidget:
        """Create a single parameter row within a group."""
        row_widget = QWidget()
        row_widget.setObjectName("parameterRow")

        border_style = "border-bottom: 1px solid #f1f5f9;" if show_border else ""
        row_widget.setStyleSheet(f"""
            QWidget#parameterRow {{
                background-color: transparent;
                {border_style}
            }}
        """)

        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(16, 12, 16, 12)
        row_layout.setSpacing(12)

        # Create label
        label_text = self._format_label(param_name, type_info)
        label = QLabel(label_text)
        label.setStyleSheet("""
            QLabel {
                font-weight: 500;
                color: palette(text);
                font-size: 13px;
            }
        """)
        label.setMinimumWidth(180)
        label.setWordWrap(True)
        row_layout.addWidget(label)

        # Add stretch
        row_layout.addStretch()

        # Create input widget
        input_widget = self.widget_factory.create_widget(
            param_name, type_info, self
        )
        self.input_widgets[param_name] = input_widget

        # Get the typed input widget and style it
        typed_input_widget = input_widget.get_widget()
        typed_input_widget.setParent(row_widget)

        # Set consistent width for input widget
        if not isinstance(typed_input_widget, QCheckBox):
            typed_input_widget.setMinimumWidth(200)

        row_layout.addWidget(typed_input_widget)
        return row_widget

    def get_values(self) -> Dict[str, Any]:
        """Get all current values from the form."""
        return {
            name: widget.get_value()
            for name, widget in self.input_widgets.items()
        }

    def set_values(self, values: Dict[str, Any]) -> None:
        """Set values in the form."""
        for name, value in values.items():
            if name in self.input_widgets:
                self.input_widgets[name].set_value(value)

    def validate(self) -> Tuple[bool, Dict[str, str]]:
        """Validate all inputs in the form."""
        errors = {}
        all_valid = True

        for name, widget in self.input_widgets.items():
            result = widget.validate()
            if not result.is_valid:
                errors[name] = result.error
                all_valid = False

        return all_valid, errors

    def get_typed_values(self) -> Dict[str, Any]:
        """Get values cast to their correct types."""
        typed_values = {}
        for name, widget in self.input_widgets.items():
            raw_value = widget.get_value()
            try:
                typed_value = widget.cast_to_type(raw_value)
                typed_values[name] = typed_value
            except ValueError:
                # Keep raw value if casting fails
                typed_values[name] = raw_value

        return typed_values

    def construct_object(self) -> Any:
        """Construct the object using the current form values."""
        # Validate first
        is_valid, errors = self.validate()
        if not is_valid:
            error_msg = "\n".join(f"{k}: {v}" for k, v in errors.items())
            raise ValueError(f"Validation failed:\n{error_msg}")

        # Get typed values
        values = self.get_typed_values()

        # Call the callable with the values
        try:
            return self.callable_obj(**values)
        except Exception as e:
            raise TypeError(f"Failed to construct object: {e}")


def create_form_for_callable(callable_obj: Callable,
                             group_mapping: Dict[str, List[str]] = None,
                             parent: QWidget = None) -> DynamicFormWidget:
    """
    Convenience function to create a form widget for any callable.

    Args:
        callable_obj: Function, class, or callable to create form for
        group_mapping: Optional grouping configuration
        parent: Parent widget

    Returns:
        DynamicFormWidget instance
    """
    return DynamicFormWidget(callable_obj, group_mapping=group_mapping,
                             parent=parent)


def create_callable_from_instance(instance: Any) -> Callable:
    """
    Create a callable that uses the current values of an instance as default arguments.

    This factory inspects an object instance and creates a callable where:
    - The signature matches the original class/callable
    - Default values are set to the current attribute values of the instance
    - All class metadata and attributes are preserved

    Args:
        instance: An object instance (dataclass, regular class, etc.)

    Returns:
        A callable that can be used with form factories, with defaults set to instance values

    Example:
        >>> @dataclass
        >>> class Settings:
        >>>     width: int = 100
        >>>     height: int = 200
        >>>
        >>> current_settings = Settings(width=500, height=300)
        >>> callable_with_current = create_callable_from_instance(current_settings)
        >>> # Now callable_with_current has width=500, height=300 as defaults
    """
    # Get the class of the instance
    cls = type(instance)

    # Get the signature of the class's __init__ method
    sig = inspect.signature(cls)

    # Build new parameters with current instance values as defaults
    new_params = []

    for param_name, param in sig.parameters.items():
        if param_name == 'self':
            continue

        # Get the current value from the instance
        try:
            current_value = getattr(instance, param_name)
        except AttributeError:
            # If attribute doesn't exist, keep original default
            current_value = param.default if param.default != inspect.Parameter.empty else None

        # Unwrap Optional types to get base type for annotation
        original_annotation = param.annotation
        if original_annotation != inspect.Parameter.empty:
            base_annotation, is_optional = unwrap_optional(original_annotation)
        else:
            base_annotation = original_annotation

        # Create new parameter with current value as default and unwrapped annotation
        new_param = param.replace(default=current_value,
                                  annotation=base_annotation)
        new_params.append(new_param)

    # Create new signature with updated defaults
    new_sig = sig.replace(parameters=new_params)

    # Create a wrapper class that inherits from the original
    # This preserves isinstance checks and all class attributes
    class CallableWrapper(cls):
        """Wrapper that preserves all class metadata while updating defaults."""
        pass

    # Copy the original class name and module
    CallableWrapper.__name__ = cls.__name__
    CallableWrapper.__qualname__ = cls.__qualname__
    CallableWrapper.__module__ = cls.__module__

    # Update the signature
    CallableWrapper.__signature__ = new_sig

    # Update annotations to use unwrapped types
    new_annotations = {}
    for param_name, param in new_sig.parameters.items():
        if param.annotation != inspect.Parameter.empty:
            new_annotations[param_name] = param.annotation
    CallableWrapper.__annotations__ = new_annotations

    return CallableWrapper


def create_callable_from_dataclass_instance(instance: Any) -> Callable:
    """
    Optimized version specifically for dataclass instances.

    This creates a new dataclass class that:
    - Uses the current instance values as field defaults
    - Unwraps Optional types to their base types
    - Preserves all decorator metadata and class attributes

    Args:
        instance: A dataclass instance

    Returns:
        A callable (class) with defaults set to current instance values
    """
    if not is_dataclass(instance):
        raise TypeError(f"Expected dataclass instance, got {type(instance)}")

    cls = type(instance)

    # Get all dataclass fields
    dataclass_fields = fields(instance)

    # Create new parameters and annotations with current values and unwrapped types
    params = []
    annotations = {}

    for field in dataclass_fields:
        current_value = getattr(instance, field.name)

        # Unwrap Optional to get the base type for annotation
        base_type, is_optional = unwrap_optional(field.type)

        # Create parameter with unwrapped type and current value
        param = inspect.Parameter(
            field.name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=current_value,
            annotation=base_type
        )
        params.append(param)
        annotations[field.name] = base_type

    # Create new signature
    new_sig = inspect.Signature(params)

    # Create a wrapper class that inherits from the original
    # This is crucial - it makes isinstance checks work and preserves all class behavior
    class DataclassWrapper(cls):
        """Wrapper that preserves all dataclass metadata while updating defaults."""
        pass

    # Update the wrapper's annotations to use unwrapped types
    # This must be done AFTER class creation to override inherited annotations
    DataclassWrapper.__annotations__ = annotations.copy()
    DataclassWrapper.__signature__ = new_sig

    # Preserve class metadata
    DataclassWrapper.__name__ = cls.__name__
    DataclassWrapper.__qualname__ = cls.__qualname__
    DataclassWrapper.__module__ = cls.__module__
    DataclassWrapper.__doc__ = cls.__doc__

    # Update __init__ signature to reflect unwrapped types
    if hasattr(DataclassWrapper.__init__, '__wrapped__'):
        # Handle dataclass-wrapped __init__
        DataclassWrapper.__init__.__signature__ = new_sig
    else:
        # Wrap __init__ with new signature
        original_init = DataclassWrapper.__init__

        def new_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)

        new_init.__signature__ = new_sig
        DataclassWrapper.__init__ = new_init

    return DataclassWrapper
