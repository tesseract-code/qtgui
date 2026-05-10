from typing import Optional, Union

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import QToolButton, QSizePolicy, QWidget

from qtgui.icons import _get_fill_icon


class TitleFrame(QtWidgets.QFrame):
    """
    Clickable header frame for a collapsible dropdown.

    Displays a title label, an optional leading icon, and (when the dropdown
    is collapsible) a trailing arrow button that reflects the expanded /
    collapsed state.
    """

    clicked = QtCore.pyqtSignal()

    def __init__(
            self,
            parent: Optional[QtWidgets.QWidget] = None,
            title: str = "",
            icon: Optional[QIcon] = None,
            height: int = 24,
            is_collapsible: bool = True,
    ) -> None:
        super().__init__(parent=parent)
        self._height = height
        self._is_collapsible = is_collapsible
        self._setup_ui(title, icon)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _setup_ui(self, title: str, icon: Optional[QIcon]) -> None:
        """Build and arrange all child widget."""
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(5)

        # --- Optional leading icon ---
        if icon:
            icon_btn = QtWidgets.QToolButton()
            icon_btn.setFixedSize(self._height, self._height)
            icon_btn.setIconSize(QSize(int(self._height * 0.7),
                                       int(self._height * 0.7)))
            icon_btn.setStyleSheet(
                "QToolButton { border: none; background: none; "
                "padding: 0px; margin: 0px; }"
            )
            icon_btn.setIcon(icon)
            icon_btn.clicked.connect(self.clicked.emit)
            layout.addWidget(icon_btn)

        # --- Title label ---
        self.title_label = QtWidgets.QLabel(title)
        font = self.title_label.font()
        font.setWeight(QFont.Weight.Bold)
        font.setPointSize(max(1, self._height // 2))
        self.title_label.setFont(font)
        self.title_label.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title_label)

        # Spacer pushes the arrow to the right edge.
        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(spacer)

        # --- Optional trailing arrow ---
        if self._is_collapsible:
            self.arrow = QToolButton()
            self.arrow.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.arrow.setCheckable(True)
            self.arrow.setContentsMargins(0, 0, 0, 0)
            self.arrow.setFixedSize(self._height, self._height)
            self.arrow.setIconSize(QSize(self._height, self._height))
            self.arrow.setStyleSheet(
                "QToolButton { border: none; background: none; "
                "padding: 0px; margin: 0px; }"
            )
            # Start in collapsed state (arrow pointing down = will expand).
            self.arrow.setIcon(
                _get_fill_icon(
                    "arrow-drop-down",
                    QSize(256, 256),
                    self.palette().text().color(),
                )
            )
            self.arrow.clicked.connect(self.clicked.emit)
            layout.addWidget(self.arrow)

        self.setStyleSheet(
            "background-color: palette(base); color: palette(text); "
            "border-radius: 10px;"
        )
        self.setMinimumHeight(40)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_arrow(self, is_collapsed: bool) -> None:
        """
        Update the arrow icon to reflect *is_collapsed*.

        Safely does nothing when the frame was created with
        ``is_collapsible=False``.
        """
        if not self._is_collapsible or not hasattr(self, "arrow"):
            return
        icon_name = (
            "arrow-drop-down" if is_collapsed else "arrow-drop-up"
        )
        self.arrow.setIcon(
            _get_fill_icon(icon_name, QSize(256, 256), self.palette().text(

            ).color())
        )

    def setMaximumHeight(self, maxh: int) -> None:
        """Keep the title label in sync when the frame height changes."""
        self._height = maxh
        if hasattr(self, "title_label"):
            self.title_label.setMaximumHeight(maxh)
        super().setMaximumHeight(maxh)

    # ------------------------------------------------------------------
    # Event overrides
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class Dropdown(QtWidgets.QWidget):
    """
    Collapsible dropdown container with optional scroll area and animation.

    Signals
    -------
    toggled(bool)
        Emitted after each state change.  ``True`` means the widget is now
        *collapsed*.
    content_changed()
        Emitted whenever the content area is modified.
    """

    toggled = QtCore.pyqtSignal(bool)
    content_changed = QtCore.pyqtSignal()

    def __init__(
            self,
            title: Optional[str] = None,
            title_icon: Optional[QIcon] = None,
            scroll_area: bool = False,
            has_content_frame: bool = True,
            parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._scroll_area = scroll_area
        self._has_content_frame = has_content_frame
        self._is_collapsed = True

        self.title_frame: Optional[TitleFrame] = None
        self._content: Optional[Union[QtWidgets.QWidget,
        QtWidgets.QScrollArea]] = None

        self._setup_ui(title, title_icon)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _setup_ui(
            self, title: Optional[str], title_icon: Optional[QIcon]
    ) -> None:
        """Build the title frame and content area."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.title_frame = TitleFrame(
            title=title or "",
            icon=title_icon,
            parent=self,
        )
        self.title_frame.clicked.connect(self.toggle)
        layout.addWidget(self.title_frame)

        self._create_content_area()
        self._content.setVisible(not self._is_collapsed)
        layout.addWidget(self._content)

        if self._has_content_frame:
            self._apply_content_styling()

    def _create_content_area(self) -> None:
        """Instantiate the correct content container based on configuration."""
        if self._scroll_area:
            self._content = QtWidgets.QScrollArea(self)
            self._content.setWidgetResizable(False)
            self._content.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._content.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Minimum,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
        else:
            self._content = QtWidgets.QFrame(self)
            content_layout = QtWidgets.QVBoxLayout(self._content)
            content_layout.setContentsMargins(10, 10, 10, 10)
            self._content.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Expanding,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )

    def _apply_content_styling(self) -> None:
        """Apply a subtle border to visually group the content area."""
        self._content.setObjectName("dropDownContentWidget")
        self._content.setStyleSheet(
            "#dropDownContentWidget { border: 1px solid palette(shadow); }"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_collapsed(self) -> bool:
        """``True`` when the content area is hidden."""
        return self._is_collapsed

    @property
    def content_widget(self) -> Optional[QtWidgets.QWidget]:
        """The internal content container (frame or scroll area)."""
        return self._content

    def add_content_widget(self, widget: QtWidgets.QWidget) -> None:
        """Append *widget* to the content area."""
        if self._scroll_area:
            self._content.setWidget(widget)
        else:
            self._content.layout().addWidget(widget)
        self.content_changed.emit()

    def remove_content_widget(self, widget: QtWidgets.QWidget) -> None:
        """Remove *widget* from the content area (no-op for scroll areas)."""
        if not self._scroll_area and self._content.layout():
            self._content.layout().removeWidget(widget)
            widget.setParent(None)
            self.content_changed.emit()

    def clear_content(self) -> None:
        """Remove all child widget from the content area."""
        if self._scroll_area:
            self._content.setWidget(None)
        else:
            layout = self._content.layout()
            if layout:
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().setParent(None)
        self.content_changed.emit()

    def drop_down(self) -> None:
        """Expand the dropdown."""
        if not self._is_collapsed:
            return
        self._is_collapsed = False
        self.title_frame.set_arrow(self._is_collapsed)
        self._content.setVisible(True)
        self.toggled.emit(False)

    def collapse(self) -> None:
        """Collapse the dropdown."""
        if self._is_collapsed:
            return
        self._is_collapsed = True
        self.title_frame.set_arrow(self._is_collapsed)
        self._content.setVisible(False)
        self.toggled.emit(True)

    @QtCore.pyqtSlot()
    def toggle(self) -> None:
        """Toggle between expanded and collapsed states."""
        if self._is_collapsed:
            self.drop_down()
        else:
            self.collapse()

    def set_title(self, title: str) -> None:
        """Update the displayed title text."""
        if self.title_frame and hasattr(self.title_frame, "title_label"):
            self.title_frame.title_label.setText(title)

    def get_title(self) -> str:
        """Return the current title text."""
        if self.title_frame and hasattr(self.title_frame, "title_label"):
            return self.title_frame.title_label.text()
        return ""
