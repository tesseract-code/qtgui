"""
PyQt6 Dynamic Widget Factory for Type-based Form Generation

Integrates with the SignatureMapper to automatically generate form widget
based on function/class signatures with type validation and casting.
"""
import logging
from typing import Any, get_origin, Union, get_args, List

from PyQt6.QtWidgets import (
    QWidget
)

from qtgui.form.input.base import BaseInputWidget
from qtgui.form.strategy.base import WidgetCreationStrategy
from qtgui.form.strategy.boolean import BooleanWidgetStrategy
from qtgui.form.strategy.color import ColorWidgetStrategy
from qtgui.form.strategy.enum import EnumWidgetStrategy
from qtgui.form.strategy.fallback import FallbackWidgetStrategy
from qtgui.form.strategy.float import FloatWidgetStrategy
from qtgui.form.strategy.integer import IntegerWidgetStrategy
from qtgui.form.strategy.list import ListWidgetStrategy
from qtgui.form.strategy.string import StringWidgetStrategy

logger = logging.getLogger(__name__)

class WidgetFactory:
    """
    Factory for creating input widget based on type information.
    Prioritizes specific type detection over generic type matching.
    """

    def __init__(self):
        # Strategies that handle specific complex types (like Color)
        self._specific_strategies: List[WidgetCreationStrategy] = []
        # Strategies for basic types
        self._basic_strategies: List[WidgetCreationStrategy] = []
        # Generic fallback strategies
        self._generic_strategies: List[WidgetCreationStrategy] = []

        # Register strategies in priority order

        # 1. Specific strategies first (Color, etc.)
        self._specific_strategies = [
            ColorWidgetStrategy(),  # Handles Color type specifically
        ]

        # 2. Basic type strategies
        self._basic_strategies = [
            IntegerWidgetStrategy(),
            FloatWidgetStrategy(),
            BooleanWidgetStrategy(),
            EnumWidgetStrategy(),
            ListWidgetStrategy(),
        ]

        # 3. Generic strategies last
        self._generic_strategies = [
            StringWidgetStrategy(),  # String strategy comes after Color
            FallbackWidgetStrategy(),
        ]

    def register_strategy(self, strategy: WidgetCreationStrategy,
                          strategy_type: str = "basic") -> None:
        """
        Register a custom widget creation strategy.

        Args:
            strategy: The strategy to register
            strategy_type: "specific" for complex types, "basic" for basic types,
                          "generic" for generic strategies
        """
        if strategy_type == "specific":
            self._specific_strategies.insert(0, strategy)
        elif strategy_type == "basic":
            self._basic_strategies.insert(0, strategy)
        else:  # generic
            self._generic_strategies.insert(0, strategy)

    def create_widget(self, param_name: str, type_info: Any,
                      parent: QWidget = None) -> BaseInputWidget:
        """
        Create an input widget for the given parameter.
        """
        # First, try specific strategies (like Color)
        for strategy in self._specific_strategies:
            if strategy.can_handle(type_info):
                return strategy.create_widget(param_name, type_info, parent)

        # Then try basic type strategies
        for strategy in self._basic_strategies:
            if strategy.can_handle(type_info):
                return strategy.create_widget(param_name, type_info, parent)

        # Finally try generic strategies
        for strategy in self._generic_strategies:
            if strategy.can_handle(type_info):
                return strategy.create_widget(param_name, type_info, parent)

        # Fallback
        raise RuntimeError("No strategy could handle type")


def unwrap_optional(type_hint: Any) -> tuple[Any, bool]:
    """
    Unwrap Optional[T] to get the base type T.

    Returns:
        Tuple of (base_type, is_optional)

    Examples:
        Optional[int] -> (int, True)
        int -> (int, False)
        Union[str, None] -> (str, True)
        Union[int, str] -> (Union[int, str], False)
    """
    origin = get_origin(type_hint)

    # Check if it's a Union type
    if origin is Union:
        args = get_args(type_hint)

        # Check if it's Optional (Union with None)
        if type(None) in args:
            # Remove None from the args
            non_none_args = [arg for arg in args if arg is not type(None)]

            # If there's only one non-None type, that's our base type
            if len(non_none_args) == 1:
                return non_none_args[0], True
            # If there are multiple non-None types, return the Union without None
            elif len(non_none_args) > 1:
                return Union.__getitem__(tuple(non_none_args)), True

    # Not an Optional type
    return type_hint, False
