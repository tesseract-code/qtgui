"""
Toolbar styling module with per-instance override support.

Global defaults are set via ``ToolBarStyleRegistry.configure()``.
Each ``StyledToolBar`` can be given its own style through a
``ToolBarStyle`` instance or keyword arguments.

If no per-instance style is provided, the global registry is used.
"""

from __future__ import annotations

from functools import cached_property
from typing import Union

from PyQt6.QtCore import Qt, QSize, QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QToolBar, QToolButton


# ── Helper ──────────────────────────────────────────────────────

def _color_to_str(color: Union[QColor, str]) -> str:
    """
    Convert a color value to a CSS-compatible string.

    Parameters
    ----------
    color : QColor or str
        A ``QColor`` instance or an already-valid CSS color string
        (e.g. ``"palette(highlight)"``, ``"#ff0000"``,
        ``"rgb(0, 120, 215)"``).

    Returns
    -------
    str
        A CSS ``rgba(r, g, b, a)`` string when *color* is a ``QColor``;
        the original string otherwise.
    """
    if isinstance(color, QColor):
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
    return color


# ── Style container ─────────────────────────────────────────────

class ToolBarStyle:
    """
    Immutable container for toolbar styling parameters.

    Instances are frozen after construction; attribute assignment raises
    ``AttributeError`` to prevent accidental mutation of shared styles
    (e.g. the global registry default).  Use :meth:`copy_with` to
    derive a modified variant.

    Parameters
    ----------
    toolbar_background_color : QColor or str, optional
        Background fill of the toolbar strip itself.
        Defaults to ``"palette(base)"``.
    btn_background_color : QColor or str, optional
        Default button background color.
        Defaults to ``"palette(button)"``.
    hover_color : QColor or str, optional
        Button background color on mouse-over.
        Defaults to ``"palette(light)"``.
    selected_color : QColor or str, optional
        Button background color when pressed or checked.
        Defaults to ``"palette(highlight)"``.
    border_color : QColor or str, optional
        Default button border color.
        Defaults to ``"palette(mid)"``.
    hover_border_color : QColor or str, optional
        Button border color on hover / pressed / checked.
        Defaults to ``"palette(highlight)"``.
    disabled_color : QColor or str, optional
        Button background color when the action is disabled.
        Defaults to ``"palette(window)"``.
    text_color : QColor or str, optional
        Button label (text) color.
        Defaults to ``"palette(text)"``.
    icon_size : QSize, optional
        Icon dimensions passed to ``QToolBar.setIconSize``.
        Defaults to ``QSize(24, 24)``.
    button_style : Qt.ToolButtonStyle, optional
        Controls whether buttons show icon only, text only, or both.
        Defaults to ``Qt.ToolButtonStyle.ToolButtonIconOnly``.
    border_radius : int, optional
        Button corner radius in pixels.  Must be >= 0.
        Defaults to ``8``.
    padding : int, optional
        Inner button padding in pixels.  Must be >= 0.
        Defaults to ``4``.
    toolbar_spacing : int, optional
        Spacing between items in the toolbar, in pixels.  Must be >= 0.
        Defaults to ``5``.
    toolbar_padding : int, optional
        Inner padding of the toolbar strip, in pixels.  Must be >= 0.
        Defaults to ``5``.

    Raises
    ------
    TypeError
        If *icon_size* is not a ``QSize``, *button_style* is not a
        ``Qt.ToolButtonStyle``, or any pixel measurement is not an
        ``int``.
    ValueError
        If any pixel measurement (*border_radius*, *padding*,
        *toolbar_spacing*, *toolbar_padding*) is negative.

    Examples
    --------
    Create a style with custom colors and icon size:

    >>> style = ToolBarStyle(
    ...     btn_background_color=QColor(240, 240, 240),
    ...     hover_color=QColor(200, 200, 255),
    ...     icon_size=QSize(32, 32),
    ... )

    Derive a variant with a different border radius:

    >>> compact = style.copy_with(border_radius=4, padding=2)
    """

    def __init__(
        self,
        toolbar_background_color: Union[QColor, str] = "palette(base)",
        btn_background_color: Union[QColor, str] = "palette(button)",
        hover_color: Union[QColor, str] = "palette(light)",
        selected_color: Union[QColor, str] = "palette(highlight)",
        border_color: Union[QColor, str] = "palette(mid)",
        hover_border_color: Union[QColor, str] = "palette(highlight)",
        disabled_color: Union[QColor, str] = "palette(window)",
        text_color: Union[QColor, str] = "palette(text)",
        icon_size: QSize = QSize(24, 24),
        button_style: Qt.ToolButtonStyle = Qt.ToolButtonStyle.ToolButtonIconOnly,
        border_radius: int = 8,
        padding: int = 4,
        toolbar_spacing: int = 5,
        toolbar_padding: int = 5,
    ) -> None:
        if not isinstance(icon_size, QSize):
            raise TypeError(
                f"icon_size must be a QSize, got {type(icon_size).__name__}"
            )
        if not isinstance(button_style, Qt.ToolButtonStyle):
            raise TypeError(
                f"button_style must be a Qt.ToolButtonStyle, "
                f"got {type(button_style).__name__}"
            )
        for name, value in (
            ("border_radius", border_radius),
            ("padding", padding),
            ("toolbar_spacing", toolbar_spacing),
            ("toolbar_padding", toolbar_padding),
        ):
            if not isinstance(value, int):
                raise TypeError(
                    f"{name} must be an int, got {type(value).__name__}"
                )
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")

        # Bypass the immutability guard during __init__ only.
        _set = object.__setattr__
        _set(self, "toolbar_background_color", toolbar_background_color)
        _set(self, "btn_background_color", btn_background_color)
        _set(self, "hover_color", hover_color)
        _set(self, "selected_color", selected_color)
        _set(self, "border_color", border_color)
        _set(self, "hover_border_color", hover_border_color)
        _set(self, "disabled_color", disabled_color)
        _set(self, "text_color", text_color)
        _set(self, "icon_size", icon_size)
        _set(self, "button_style", button_style)
        _set(self, "border_radius", border_radius)
        _set(self, "padding", padding)
        _set(self, "toolbar_spacing", toolbar_spacing)
        _set(self, "toolbar_padding", toolbar_padding)

    def __setattr__(self, name: str, value: object) -> None:
        # cached_property writes directly to __dict__, bypassing this method,
        # so the stylesheet cache is not affected by this guard.
        raise AttributeError(
            f"ToolBarStyle is immutable. "
            f"Use copy_with({name}=...) to derive a modified style."
        )

    def copy_with(self, **kwargs) -> ToolBarStyle:
        """
        Return a new ``ToolBarStyle`` with selected attributes overridden.

        Parameters
        ----------
        **kwargs
            Any subset of ``ToolBarStyle`` constructor parameters.
            Unrecognised keys are silently ignored so that callers do
            not need to filter cached internal attributes (e.g.
            ``stylesheet``).

        Returns
        -------
        ToolBarStyle
            A new instance combining the current parameter values with
            *kwargs*.

        Examples
        --------
        >>> bold_borders = existing_style.copy_with(border_radius=0, padding=6)
        """
        # Exclude cached_property results (e.g. "stylesheet") so they
        # are not forwarded as unknown kwargs to __init__.
        _init_params = {
            "toolbar_background_color", "btn_background_color", "hover_color",
            "selected_color", "border_color", "hover_border_color",
            "disabled_color", "text_color", "icon_size", "button_style",
            "border_radius", "padding", "toolbar_spacing", "toolbar_padding",
        }
        current = {k: v for k, v in self.__dict__.items() if k in _init_params}
        current.update({k: v for k, v in kwargs.items() if k in _init_params})
        return ToolBarStyle(**current)

    @cached_property
    def stylesheet(self) -> str:
        """
        QSS stylesheet derived from the current style parameters.

        Computed once on first access and cached for the lifetime of
        this instance.  The cache is safe because ``ToolBarStyle`` is
        immutable.

        Returns
        -------
        str
            A Qt Style Sheet string targeting ``QToolBar`` and
            ``QToolButton``.
        """
        toolbar_bg = _color_to_str(self.toolbar_background_color)
        bg         = _color_to_str(self.btn_background_color)
        hover      = _color_to_str(self.hover_color)
        selected   = _color_to_str(self.selected_color)
        border     = _color_to_str(self.border_color)
        hover_border = _color_to_str(self.hover_border_color)
        disabled   = _color_to_str(self.disabled_color)
        text       = _color_to_str(self.text_color)

        return f"""
            QToolBar {{
                background-color: {toolbar_bg};
                border: none;
                border-radius: {self.border_radius}px;
                spacing: {self.toolbar_spacing}px;
                padding: {self.toolbar_padding}px;
            }}

            QToolButton {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {self.border_radius}px;
                padding: {self.padding}px;
                color: {text};
            }}

            QToolButton:hover {{
                background-color: {hover};
                border: 1px solid {hover_border};
            }}

            QToolButton:pressed, QToolButton:checked {{
                background-color: {selected};
                border: 1px solid {hover_border};
            }}

            QToolButton:disabled {{
                background-color: {disabled};
                border: 1px solid {border};
            }}
        """

    def apply_to(self, toolbar: QToolBar) -> None:
        """
        Apply this style to a toolbar widget in place.

        Sets the stylesheet, icon size, and tool-button display style
        on *toolbar*.

        Parameters
        ----------
        toolbar : QToolBar
            The toolbar widget to style.
        """
        toolbar.setStyleSheet(self.stylesheet)
        toolbar.setIconSize(self.icon_size)
        toolbar.setToolButtonStyle(self.button_style)


# ── Global registry ─────────────────────────────────────────────

class ToolBarStyleRegistry:
    """
    Global registry for the default toolbar style.

    Call :meth:`configure` to update the global defaults.
    Use :meth:`get_style` to retrieve the current default.
    Use :meth:`apply_to` to apply the global (or a given) style to any
    ``QToolBar``.
    """

    _global_style: ToolBarStyle = ToolBarStyle()

    @classmethod
    def configure(cls, **kwargs) -> None:
        """
        Update the global default style.

        Only the provided keyword arguments are changed; all others
        retain their current values.  Accepts the same parameters as
        :class:`ToolBarStyle`.

        Parameters
        ----------
        **kwargs
            Subset of :class:`ToolBarStyle` constructor parameters to
            override.  Unrecognised keys are silently ignored.

        Examples
        --------
        Restore built-in defaults:

        >>> ToolBarStyleRegistry.configure()

        Customise with ``QColor`` instances:

        >>> ToolBarStyleRegistry.configure(
        ...     btn_background_color=QColor(240, 240, 240),
        ...     hover_color=QColor(220, 220, 220),
        ...     selected_color=QColor(0, 120, 215),
        ...     icon_size=QSize(32, 32),
        ... )

        Customise with palette or CSS strings:

        >>> ToolBarStyleRegistry.configure(
        ...     btn_background_color="palette(button)",
        ...     hover_color="#e0e0e0",
        ...     selected_color="rgb(0, 120, 215)",
        ... )
        """
        cls._global_style = cls._global_style.copy_with(**kwargs)

    @classmethod
    def get_style(cls) -> ToolBarStyle:
        """
        Return the current global default style.

        Because ``ToolBarStyle`` is immutable, the shared instance is
        returned directly — callers cannot mutate it.

        Returns
        -------
        ToolBarStyle
            The current global default style.
        """
        return cls._global_style

    @classmethod
    def apply_to(cls, toolbar: QToolBar, style: ToolBarStyle | None = None) -> None:
        """
        Apply a style to a toolbar, falling back to the global default.

        Delegates to :meth:`ToolBarStyle.apply_to`.

        Parameters
        ----------
        toolbar : QToolBar
            The toolbar widget to style.
        style : ToolBarStyle or None, optional
            Explicit style to apply.  If ``None``, the global registry
            style is used.
        """
        effective = style if style is not None else cls._global_style
        effective.apply_to(toolbar)


# ── Styled toolbar ──────────────────────────────────────────────

class StyledToolBar(QToolBar):
    """
    A ``QToolBar`` that automatically applies registered styling.

    Parameters
    ----------
    title : str, optional
        Toolbar title used by Qt when the toolbar is floating or docked.
        Defaults to ``""``.
    parent : QWidget or None, optional
        Parent widget.  Defaults to ``None``.
    style : ToolBarStyle or None, optional
        Explicit per-instance style.  Mutually exclusive with
        *style_kwargs*; passing both raises ``ValueError``.
    **style_kwargs
        Keyword arguments forwarded to :class:`ToolBarStyle` to create
        a one-off per-instance style.  Mutually exclusive with *style*.

    Raises
    ------
    ValueError
        If both *style* and *style_kwargs* are provided.

    Examples
    --------
    Use the global registry style (default):

    >>> toolbar = StyledToolBar("Main", parent=self)

    One-off style via keyword arguments:

    >>> toolbar = StyledToolBar(
    ...     "Custom",
    ...     parent=self,
    ...     border_radius=4,
    ...     icon_size=QSize(20, 20),
    ... )

    Explicit ``ToolBarStyle`` instance:

    >>> my_style = ToolBarStyle(border_radius=0)
    >>> toolbar = StyledToolBar("Flat", parent=self, style=my_style)
    """

    def __init__(
        self,
        title: str = "",
        parent=None,
        style: ToolBarStyle | None = None,
        **style_kwargs,
    ) -> None:
        super().__init__(title, parent)

        if style is not None and style_kwargs:
            raise ValueError(
                "Provide either 'style' or keyword style arguments, not both."
            )

        if style is not None:
            self._instance_style: ToolBarStyle | None = style
        elif style_kwargs:
            self._instance_style = ToolBarStyle(**style_kwargs)
        else:
            self._instance_style = None  # fall back to global registry

        self._setup_toolbar()

    def _setup_toolbar(self) -> None:
        """Configure toolbar properties and apply the resolved style."""
        self.setMovable(False)
        self.setFloatable(False)
        ToolBarStyleRegistry.apply_to(self, self._instance_style)

    def actionEvent(self, event: QEvent) -> None:
        """
        Enable hover tracking on newly added tool buttons.

        Overrides ``QToolBar.actionEvent`` so that ``WA_Hover`` and
        mouse-tracking are activated on every ``QToolButton`` added to
        this toolbar.  Separator widgets (which yield ``None`` from
        ``widgetForAction``) are left unchanged.

        Parameters
        ----------
        event : QEvent
            The action event forwarded by Qt.
        """
        super().actionEvent(event)
        if event.type() == QEvent.Type.ActionAdded:
            widget = self.widgetForAction(event.action())
            if isinstance(widget, QToolButton):  # separators return None
                widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
                widget.setMouseTracking(True)


# ── Convenience function ────────────────────────────────────────

def configure_toolbar_style(**kwargs) -> None:
    """
    Convenience alias for :meth:`ToolBarStyleRegistry.configure`.

    Parameters
    ----------
    **kwargs
        Forwarded directly to :meth:`ToolBarStyleRegistry.configure`.
        See that method for accepted parameters and examples.
    """
    ToolBarStyleRegistry.configure(**kwargs)