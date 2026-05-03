import sys
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt

from qtcore.app import Application
from qtgui.edit import SearchLineEdit


class SearchExample(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SearchLineEdit Example")
        self.setMinimumSize(400, 120)

        layout = QVBoxLayout(self)

        # 1) Create the search input with a custom placeholder
        self.search_edit = SearchLineEdit("Filter items...")

        # 2) Label to display the live search term
        self.result_label = QLabel("Start typing to search")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.search_edit)
        layout.addWidget(self.result_label)

        # 3) React when the user types
        self.search_edit.textChanged.connect(self.on_text_changed)

    def on_text_changed(self, text):
        if text:
            self.result_label.setText(f"Searching for: '{text}'")
        else:
            self.result_label.setText("Search field is empty")


if __name__ == "__main__":
    app = Application(argv=sys.argv)
    window = SearchExample()
    window.show()
    sys.exit(app.exec())