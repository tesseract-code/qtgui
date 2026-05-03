
"""
dropdown_example.py
-------------------
Demonstrates common usage patterns for the Dropdown / TitleFrame widget.

Run with:
    python dropdown_example.py
"""

import sys

from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from qtgui.drop_down import Dropdown


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _labelled_row(label_text: str,
                  widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    """Return a small horizontal widget pairing a label with another widget."""
    row = QWidget()
    layout = QtWidgets.QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QtWidgets.QLabel(label_text))
    layout.addWidget(widget)
    layout.addStretch()
    return row


# ---------------------------------------------------------------------------
# Example 1 – plain form fields inside a dropdown
# ---------------------------------------------------------------------------

def make_personal_details_dropdown() -> Dropdown:
    """A basic dropdown containing a small form."""
    dropdown = Dropdown(title="Personal Details")

    name_edit = QtWidgets.QLineEdit()
    name_edit.setPlaceholderText("Full name")

    email_edit = QtWidgets.QLineEdit()
    email_edit.setPlaceholderText("Email address")

    dob_edit = QtWidgets.QDateEdit()
    dob_edit.setCalendarPopup(True)

    dropdown.add_content_widget(_labelled_row("Name  :", name_edit))
    dropdown.add_content_widget(_labelled_row("Email :", email_edit))
    dropdown.add_content_widget(_labelled_row("DOB   :", dob_edit))

    return dropdown


# ---------------------------------------------------------------------------
# Example 2 – scrollable list of items
# ---------------------------------------------------------------------------

def make_log_dropdown() -> Dropdown:
    """A scrollable dropdown showing a list of log entries."""
    dropdown = Dropdown(
        title="Event Log",
        scroll_area=True,
    )

    container = QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(4, 4, 4, 4)

    sample_logs = [
        "[INFO]  Application started",
        "[INFO]  Loading configuration…",
        "[WARN]  Config key 'timeout' missing – using default (30 s)",
        "[INFO]  Connected to database",
        "[DEBUG] Query executed in 12 ms",
        "[INFO]  User 'alice' logged in",
        "[DEBUG] Cache hit for key 'user:alice'",
        "[INFO]  Report generated successfully",
        "[WARN]  Disk usage above 80 %",
        "[INFO]  Scheduled task completed",
    ]

    for entry in sample_logs:
        lbl = QtWidgets.QLabel(entry)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

    container.setFixedHeight(200)
    dropdown.add_content_widget(container)
    return dropdown


# ---------------------------------------------------------------------------
# Example 3 – programmatic expand / collapse via external button
# ---------------------------------------------------------------------------

def make_settings_dropdown() -> tuple[Dropdown, QWidget]:
    """
    A dropdown whose state is also controlled by an external toolbar button.

    Returns the dropdown and a small control bar so they can be laid out
    separately.
    """
    dropdown = Dropdown(title="Advanced Settings")

    checkbox = QtWidgets.QCheckBox("Enable verbose logging")
    spin = QtWidgets.QSpinBox()
    spin.setRange(1, 120)
    spin.setSuffix(" s")
    combo = QtWidgets.QComboBox()
    combo.addItems(["Low", "Medium", "High"])

    dropdown.add_content_widget(checkbox)
    dropdown.add_content_widget(_labelled_row("Timeout :", spin))
    dropdown.add_content_widget(_labelled_row("Priority:", combo))

    # External control bar
    control_bar = QWidget()
    h = QtWidgets.QHBoxLayout(control_bar)
    h.setContentsMargins(0, 0, 0, 0)

    expand_btn = QtWidgets.QPushButton("Expand")
    collapse_btn = QtWidgets.QPushButton("Collapse")
    toggle_btn = QtWidgets.QPushButton("Toggle")
    status_lbl = QtWidgets.QLabel("State: collapsed")

    expand_btn.clicked.connect(dropdown.drop_down)
    collapse_btn.clicked.connect(dropdown.collapse)
    toggle_btn.clicked.connect(dropdown.toggle)

    def _on_toggled(is_collapsed: bool) -> None:
        status_lbl.setText(
            f"State: {'collapsed' if is_collapsed else 'expanded'}")

    dropdown.toggled.connect(_on_toggled)

    for w in (expand_btn, collapse_btn, toggle_btn, status_lbl):
        h.addWidget(w)
    h.addStretch()

    return dropdown, control_bar


# ---------------------------------------------------------------------------
# Example 4 – dynamically adding and removing content
# ---------------------------------------------------------------------------

def make_dynamic_dropdown() -> Dropdown:
    """Demonstrates add / remove / clear on a live dropdown."""
    dropdown = Dropdown(title="Dynamic Content")
    dropdown.drop_down()  # Start expanded so changes are immediately visible.

    counter = {"n": 0}

    def _add_item() -> None:
        counter["n"] += 1
        lbl = QtWidgets.QLabel(f"Item {counter['n']}")
        lbl.setObjectName(f"dynamic_item_{counter['n']}")
        dropdown.add_content_widget(lbl)

    def _clear_items() -> None:
        dropdown.clear_content()
        # Re-add the button row after clearing.
        dropdown.add_content_widget(_make_button_row())

    def _make_button_row() -> QWidget:
        row = QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        add_btn = QtWidgets.QPushButton("Add item")
        clear_btn = QtWidgets.QPushButton("Clear all")
        add_btn.clicked.connect(_add_item)
        clear_btn.clicked.connect(_clear_items)
        h.addWidget(add_btn)
        h.addWidget(clear_btn)
        h.addStretch()
        return row

    dropdown.add_content_widget(_make_button_row())
    return dropdown


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Dropdown – Usage Examples")
        self.setMinimumWidth(500)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # -- Example 1: form fields
        layout.addWidget(QtWidgets.QLabel("<b>Example 1 – Form fields</b>"))
        layout.addWidget(make_personal_details_dropdown())

        # -- Example 2: scrollable log
        layout.addWidget(QtWidgets.QLabel("<b>Example 2 – Scrollable list</b>"))
        layout.addWidget(make_log_dropdown())

        # -- Example 3: external controls
        layout.addWidget(
            QtWidgets.QLabel("<b>Example 3 – External controls</b>"))
        settings_dd, control_bar = make_settings_dropdown()
        layout.addWidget(control_bar)
        layout.addWidget(settings_dd)

        # -- Example 4: dynamic content
        layout.addWidget(QtWidgets.QLabel("<b>Example 4 – Dynamic content</b>"))
        layout.addWidget(make_dynamic_dropdown())

        layout.addStretch()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
