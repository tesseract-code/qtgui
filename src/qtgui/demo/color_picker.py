import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt

from qtgui.color_picker import ColorPickerButton


class DemoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ColorPickerButton Usage Example")
        self.setMinimumSize(300, 150)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # 1) Create the color picker button with a custom initial color
        self.color_picker = ColorPickerButton(
            label="Accent Color",
            initial_color="#FF5722",          # hex string
            button_size=40
        )

        # 2) Connect the colorChanged signal to update a label
        self.info_label = QLabel("Selected color will appear here.")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.color_picker.colorChanged.connect(self.on_color_changed)

        layout.addWidget(self.color_picker)
        layout.addWidget(self.info_label)

        # Show initial color info
        self.on_color_changed(self.color_picker.get_color())

    def on_color_changed(self, color):
        """Display hex and RGB values of the newly chosen color."""
        hex_str = color.name().upper()
        rgb = (color.red(), color.green(), color.blue())
        self.info_label.setText(f"Hex: {hex_str}   RGB: {rgb}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())