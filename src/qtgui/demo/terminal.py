import sys

from PyQt6.QtWidgets import QMainWindow, QApplication

from qtgui.terminal.widget import TerminalWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Terminal")
        self.resize(1100, 700)
        self.setCentralWidget(TerminalWidget())


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()