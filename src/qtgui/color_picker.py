from typing import Union, Tuple, NewType

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QAction
from PyQt6.QtWidgets import (QApplication, QWidget, QHBoxLayout, QPushButton,
                             QColorDialog, QMenu)

Color = NewType('Color', Union[
    QColor,  # Qt color object
    str,  # Hex string: "#RRGGBB" or "#RRGGBBAA"
    Tuple[int, int, int],  # RGB tuple: (r, g, b)
    Tuple[int, int, int, int],  # RGBA tuple: (r, g, b, a)
    Tuple[float, float, float, float]  # Normalized RGBA: (r, g, b, a) 0.0-1.0
])


def to_qcolor(color: Color) -> QColor:
    """Convert any supported color format to QColor"""
    if isinstance(color, QColor):
        return color

    elif isinstance(color, str):
        # Handle hex strings
        if color.startswith('#'):
            return QColor(color)
        else:
            # Try to parse as hex without #, or as color name
            return QColor(color)

    elif isinstance(color, tuple):
        if len(color) == 3:
            # RGB tuple (int)
            if all(isinstance(c, int) for c in color):
                return QColor(*color)
            # Normalized RGB (float)
            elif all(isinstance(c, float) for c in color):
                return QColor(int(color[0] * 255), int(color[1] * 255),
                              int(color[2] * 255))

        elif len(color) == 4:
            # RGBA tuple (int)
            if all(isinstance(c, int) for c in color):
                return QColor(*color)
            # Normalized RGBA (float)
            elif all(isinstance(c, float) for c in color):
                return QColor(int(color[0] * 255), int(color[1] * 255),
                              int(color[2] * 255), int(color[3] * 255))

    # Fallback - try to create QColor from string representation
    try:
        return QColor(str(color))
    except:
        raise ValueError(f"Cannot convert {color} to QColor")


class ColorPickerButton(QWidget):
    """Uniform square color picker button with copy options"""

    colorChanged = pyqtSignal(QColor)

    def __init__(self, label="Color",
                 initial_color: Color = QColor(130, 53, 220), button_size=30,
                 parent=None):
        super().__init__(parent=parent)
        self._current_color = to_qcolor(initial_color)
        self.label = label
        self.button_size = button_size

        self._setup_ui()
        self._setup_context_menu()
        self._update_display()

    def _setup_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Uniform square color button
        self.color_button = QPushButton()
        self.color_button.setFixedSize(self.button_size, self.button_size)
        self.color_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_button.clicked.connect(self._launch_color_dialog)
        self.color_button.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.color_button.customContextMenuRequested.connect(
            self._show_context_menu)

        # layout.addWidget(self.label_widget)
        layout.addWidget(self.color_button)

        self.setLayout(layout)

    def _setup_context_menu(self):
        """Setup the context menu for copying color values"""
        self.context_menu = QMenu(self)

        # Copy Hex action
        self.copy_hex_action = QAction("Copy Hex", self)
        self.copy_hex_action.triggered.connect(self._copy_hex_to_clipboard)
        self.context_menu.addAction(self.copy_hex_action)

        # Copy RGB action
        self.copy_rgb_action = QAction("Copy RGB", self)
        self.copy_rgb_action.triggered.connect(self._copy_rgb_to_clipboard)
        self.context_menu.addAction(self.copy_rgb_action)

        # Separator
        self.context_menu.addSeparator()

        # Edit color action
        self.edit_color_action = QAction("Edit Color...", self)
        self.edit_color_action.triggered.connect(self._launch_color_dialog)
        self.context_menu.addAction(self.edit_color_action)

    def _show_context_menu(self, position):
        """Show context menu at cursor position"""
        self.context_menu.exec(self.mapToGlobal(position))

    def _copy_hex_to_clipboard(self):
        """Copy current color hex value to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self._current_color.name().upper())

    def _copy_rgb_to_clipboard(self):
        """Copy current color as RGB values to clipboard"""
        r, g, b = self._current_color.red(), self._current_color.green(), self._current_color.blue()
        rgb_text = f"rgb({r}, {g}, {b})"
        clipboard = QApplication.clipboard()
        clipboard.setText(rgb_text)

    def _launch_color_dialog(self, event=None):
        """Launch Qt's built-in color dialog"""
        dialog = QColorDialog(self._current_color)
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        dialog.setWindowTitle(f"Choose {self.label}")

        if dialog.exec() == QColorDialog.DialogCode.Accepted:
            selected_color = dialog.selectedColor()
            if selected_color.isValid():
                self._set_color(selected_color)

    def _set_color(self, color: QColor):
        """Set the current color and update display"""
        self._current_color = color
        self._update_display()
        self.colorChanged.emit(color)

    def _update_display(self):
        """Update the color button background"""
        border_color = "#666666" if self._current_color.lightness() > 180 else "#cccccc"

        self.color_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._current_color.name()};
                border: 2px solid {border_color};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: #333333;
            }}
        """)

    # Public API
    def get_color(self) -> QColor:
        """Get the current selected color as QColor"""
        return self._current_color

    def set_color(self, color: Color):
        """Set the current color from any supported format"""
        self._set_color(to_qcolor(color))

    def get_hex(self) -> str:
        """Get current color as hex string"""
        return self._current_color.name().upper()

    def get_rgb(self) -> Tuple[int, int, int]:
        """Get current color as RGB tuple"""
        return (self._current_color.red(), self._current_color.green(),
                self._current_color.blue())

    def get_rgba(self) -> Tuple[int, int, int, int]:
        """Get current color as RGBA tuple"""
        return (self._current_color.red(), self._current_color.green(),
                self._current_color.blue(), self._current_color.alpha())
