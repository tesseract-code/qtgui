import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt

from qtgui.joystick import JoystickWidget, compute_joystick_displacement


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Joystick Widget Example")
        self.setGeometry(100, 100, 400, 450)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create the joystick widget with custom step size and batch interval
        self.joystick = JoystickWidget(step_size=2.0, batch_interval_ms=50)
        layout.addWidget(self.joystick)

        # Label to display batched movement data
        self.info_label = QLabel("Move the joystick or use arrow keys")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_label)

        # Connect signals
        self.joystick.button_pressed.connect(self.on_button_pressed)
        self.joystick.movements_batched.connect(self.on_movements_batched)

    def on_button_pressed(self, direction):
        """Called when a directional button is pressed (mouse or keyboard)."""
        print(f"Button pressed: {direction.name}")

    def on_movements_batched(self, moves):
        """
        Called periodically with a list of accumulated JoystickMove objects.
        Use compute_joystick_displacement to calculate net displacement.
        """
        if not moves:
            return

        dx, dy = compute_joystick_displacement(moves)
        self.info_label.setText(
            f"Moves: {len(moves)} | Total dx: {dx:.2f}, dy: {dy:.2f}"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())