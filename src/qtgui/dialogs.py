import logging
from abc import abstractmethod
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QDialog, QListWidget, QStackedWidget, QListWidgetItem,
    QHBoxLayout, QPushButton, QWidget, QToolButton, QVBoxLayout, QLabel
)

from cross_platform.dev.icons_legacy.svg_path import get_icon, IconType
from qtcore.meta import QABCMeta

logger = logging.getLogger(__name__)

# Stylesheet constants
NAV_LIST_STYLESHEET = """
    QListWidget#navigationList {
        background-color: palette(window);
        border-right: 1px solid palette(mid);
        outline: none;
        padding: 0px;
    }

    QListWidget#navigationList::item {
        background-color: transparent;
        border: none;
        border-radius: 0px;
        padding: 12px 16px;
        margin: 0px;
        color: palette(text);
        font-size: 13px;
    }

    QListWidget#navigationList::item:hover {
        background-color: palette(light);
    }

    QListWidget#navigationList::item:selected {
        background-color: palette(highlight);
        color: palette(highlighted-text);
        border-left: 3px solid palette(accent);
        font-weight: bold;
    }

    QListWidget#navigationList::item:selected:hover {
        background-color: palette(highlight);
    }
"""

NAV_LIST_COLLAPSED_STYLESHEET = """
    QListWidget#navigationList {
        background-color: palette(window);
        border: none;
        outline: none;
        padding: 0px;
    }

    QListWidget#navigationList::item {
        background-color: transparent;
        border: none;
        border-radius: 4px;
        padding: 8px;
        margin: 4px;
        color: palette(text);
    }

    QListWidget#navigationList::item:hover {
        background-color: palette(light);
    }

    QListWidget#navigationList::item:selected {
        background-color: palette(highlight);
        color: palette(highlighted-text);
    }

    QListWidget#navigationList::item:selected:hover {
        background-color: palette(highlight);
    }
"""

TOGGLE_BUTTON_STYLESHEET = """
    QPushButton#toggleButton {
        background-color: transparent;
        border: none;
        padding: 8px;
        border-radius: 4px;
    }

    QPushButton#toggleButton:hover {
        background-color: palette(light);
    }

    QPushButton#toggleButton:pressed {
        background-color: palette(mid);
    }
"""

MENU_HEADER_STYLESHEET = """
    QWidget#menuHeader {
        background-color: palette(window);
        border-right: 1px solid palette(mid);
    }
"""

BUTTON_BAR_STYLESHEET = """
    QWidget#buttonBar {
        background-color: palette(window);
        border-top: none;
        padding: 8px;
    }
"""

APPLY_BUTTON_STYLESHEET = """
    QPushButton#applyButton {
        background-color: palette(highlight);
        color: palette(highlighted-text);
        border: none;
        border-radius: 4px;
        padding: 8px 24px;
        font-weight: bold;
    }

    QPushButton#applyButton:hover {
        background-color: palette(accent);
    }

    QPushButton#applyButton:pressed {
        background-color: palette(dark);
    }
"""


class NavigableDialog(QDialog, metaclass=QABCMeta):
    """Base class for settings dialogs with vertical navigation."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent=parent)
        self.nav_collapsed = False
        self.nav_items_data: List[Tuple[IconType, str]] = []

        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )

        self._setup_ui()
        self.resize(720, 500)

    def _setup_ui(self):
        """Set up the dialog UI with modern vertical navigation."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        content_layout = self._create_content_layout()
        main_layout.addLayout(content_layout)

        button_bar = self._create_button_bar()
        main_layout.addWidget(button_bar)

    def _create_content_layout(self) -> QHBoxLayout:
        """Create the main content layout with navigation and pages."""
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        nav_container = QWidget()
        nav_container_layout = QVBoxLayout(nav_container)
        nav_container_layout.setContentsMargins(0, 0, 0, 0)
        nav_container_layout.setSpacing(0)

        menu_header = self._create_menu_header()
        nav_container_layout.addWidget(menu_header)

        self.nav_list = self._create_navigation_list()
        nav_container_layout.addWidget(self.nav_list)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentStack")

        self.add_pages()

        self.nav_list.currentRowChanged.connect(
            self.content_stack.setCurrentIndex)
        self.nav_list.setCurrentRow(0)

        content_layout.addWidget(nav_container)
        content_layout.addWidget(self.content_stack, 1)

        return content_layout

    def _create_menu_header(self) -> QWidget:
        """Create the menu header bar with title and toggle button."""
        menu_header = QWidget()
        menu_header.setObjectName("menuHeader")
        menu_header.setStyleSheet(MENU_HEADER_STYLESHEET)
        menu_header.setFixedHeight(60)

        header_layout = QHBoxLayout(menu_header)

        self.title_icon_label = QWidget()
        title_icon_layout = QHBoxLayout(self.title_icon_label)
        title_icon_layout.setContentsMargins(0, 0, 0, 0)
        title_icon_layout.setSpacing(4)

        icon_label = QToolButton()
        icon_label.setCheckable(False)
        icon_label.setIcon(self.get_title_icon())
        icon_label.setStyleSheet("border: none; background: transparent;")
        title_icon_layout.addWidget(icon_label)

        title_label = QLabel(self.get_title_text())
        font = title_label.font()
        font.setBold(True)
        title_label.setFont(font)
        title_icon_layout.addWidget(title_label)

        header_layout.addWidget(self.title_icon_label)
        header_layout.addStretch()

        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("toggleButton")
        self.toggle_button.setToolTip("Collapse/Expand Menu")
        self.toggle_button.setIcon(
            get_icon(IconType.SIDEBAR_FOLD, QSize(256, 256),
                     self.palette().text().color())
        )
        self.toggle_button.setStyleSheet(TOGGLE_BUTTON_STYLESHEET)
        self.toggle_button.clicked.connect(self._toggle_navigation)

        header_layout.addWidget(self.toggle_button)

        return menu_header

    def _create_navigation_list(self) -> QListWidget:
        """Create and style the navigation list widget."""
        nav_list = QListWidget()
        nav_list.setObjectName("navigationList")
        nav_list.setMinimumWidth(200)
        nav_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        nav_list.setSpacing(0)
        nav_list.setStyleSheet(NAV_LIST_STYLESHEET)
        return nav_list

    def _create_button_bar(self) -> QWidget:
        """Create the bottom button bar."""
        button_bar = QWidget()
        button_bar.setObjectName("buttonBar")
        button_bar.setStyleSheet(BUTTON_BAR_STYLESHEET)

        layout = QHBoxLayout(button_bar)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.addStretch()

        apply_btn = self._create_apply_button()
        layout.addWidget(apply_btn)

        return button_bar

    def _create_apply_button(self) -> QPushButton:
        """Create and configure the apply button."""
        apply_btn = QPushButton(self.get_apply_button_text())
        apply_btn.setIcon(
            get_icon(IconType.SUCCESS, QSize(256, 256),
                     self.palette().buttonText().color())
        )
        apply_btn.setObjectName("applyButton")
        apply_btn.clicked.connect(self.on_apply)
        apply_btn.setMinimumWidth(100)
        apply_btn.setStyleSheet(APPLY_BUTTON_STYLESHEET)
        return apply_btn

    def _toggle_navigation(self):
        """Toggle between expanded and collapsed navigation view."""
        self.nav_collapsed = not self.nav_collapsed
        menu_icon_type = (IconType.SIDEBAR_UNFOLD
                          if self.nav_collapsed else IconType.SIDEBAR_FOLD)

        self.toggle_button.setIcon(
            get_icon(menu_icon_type, QSize(256, 256),
                     self.palette().text().color())
        )

        if self.nav_collapsed:
            self.nav_list.setMaximumWidth(60)
            self.nav_list.setMinimumWidth(60)
            self.nav_list.setStyleSheet(NAV_LIST_COLLAPSED_STYLESHEET)
            self.title_icon_label.hide()

            for i in range(self.nav_list.count()):
                item = self.nav_list.item(i)
                if i < len(self.nav_items_data):
                    # FIX 3: Re-render icon from IconType against the current
                    # palette rather than reusing a stale pre-built QIcon.
                    icon_type, text = self.nav_items_data[i]
                    item.setIcon(
                        get_icon(icon_type, QSize(256, 256),
                                 self.palette().text().color())
                    )
                    item.setText("")
                    item.setToolTip(text)
                    item.setSizeHint(QSize(60, 48))
        else:
            self.nav_list.setMaximumWidth(200)
            self.nav_list.setMinimumWidth(180)
            self.nav_list.setStyleSheet(NAV_LIST_STYLESHEET)
            self.title_icon_label.show()

            for i in range(self.nav_list.count()):
                item = self.nav_list.item(i)
                if i < len(self.nav_items_data):
                    # FIX 3: Same — fresh render on expand.
                    icon_type, text = self.nav_items_data[i]
                    item.setIcon(
                        get_icon(icon_type, QSize(256, 256),
                                 self.palette().text().color())
                    )
                    item.setText(text)
                    item.setToolTip("")
                    item.setSizeHint(QSize())

    def add_page(self, icon: IconType, title: str, widget: QWidget):
        """Add a page to the navigation and content stack.

        Args:
            icon: IconType for the navigation item
            title: Display title for the navigation item
            widget: Widget to display when this page is selected
        """
        # FIX 3: Persist the IconType, not the rendered QIcon, so the icon
        # colour can always be recomputed against the live palette.
        self.nav_items_data.append((icon, title))
        item = QListWidgetItem(
            get_icon(icon, QSize(256, 256), self.palette().text().color()),
            title
        )
        self.nav_list.addItem(item)
        self.content_stack.addWidget(widget)

    def show_centered(self, parent_widget: Optional[QWidget]):
        """Show dialog centered on parent widget."""
        if parent_widget:
            parent_rect = parent_widget.rect()
            parent_center = parent_widget.mapToGlobal(parent_rect.center())

            # FIX 1: sizeHint() reflects the intended size before the window
            # is shown; self.rect() is (0, 0, 0, 0) at this point and would
            # place the dialog at the wrong position.
            hint = self.sizeHint()
            x = parent_center.x() - hint.width() // 2
            y = parent_center.y() - hint.height() // 2

            self.move(x, y)

        self.exec()

    # ------------------------------------------------------------------
    # Abstract methods — must be implemented by every subclass
    # ------------------------------------------------------------------

    @abstractmethod
    def add_pages(self):
        """Add all pages via self.add_page(). Must be implemented."""
        pass

    @abstractmethod
    def on_apply(self):
        """Handle apply button click. Must be implemented."""
        pass

    # ------------------------------------------------------------------
    # FIX 4: Hook methods are now abstract so subclasses are reminded to
    # provide their own values rather than silently using the defaults.
    # ------------------------------------------------------------------

    @abstractmethod
    def get_title_icon(self):
        """Return the QIcon shown in the header. Must be implemented.

        Example::

            return get_icon(IconType.SETTINGS, QSize(256, 256),
                            self.palette().text().color())
        """
        pass

    @abstractmethod
    def get_title_text(self) -> str:
        """Return the header label text. Must be implemented."""
        pass

    @abstractmethod
    def get_apply_button_text(self) -> str:
        """Return the apply button label. Must be implemented."""
        pass
