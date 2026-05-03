"""
Usage example for ScientificLineEdit.

Demonstrates a small unit-conversion panel with three fields:
  - Farads  (very small numbers  → scientific notation)
  - Microfarads (mid-range)
  - Picofarads (large integers)

Editing any field recalculates and updates the other two,
showing how valueChanged integrates into a real workflow.
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from qtgui.edit import ScientificLineEdit


class CapacitanceConverter(QMainWindow):
    """Convert between Farads, Microfarads, and Picofarads."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Capacitance Converter")
        self._updating = False  # Guard against cascading updates

        # --- Widgets ---
        self.edit_f = ScientificLineEdit()  # Farads      (e.g. 4.700e-06)
        self.edit_uf = ScientificLineEdit()  # Microfarads (e.g. 4.700)
        self.edit_pf = ScientificLineEdit()  # Picofarads  (e.g. 4700.000)
        self.status = QLabel("Edit any field to convert.")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Seed with a sensible starting value (4.7 µF ceramic cap)
        self.edit_f.setValue(4.7e-6)
        self.edit_uf.setValue(4.7)
        self.edit_pf.setValue(4700.0)

        # --- Connections ---
        self.edit_f.valueChanged.connect(self._from_farads)
        self.edit_uf.valueChanged.connect(self._from_microfarads)
        self.edit_pf.valueChanged.connect(self._from_picofarads)

        # --- Layout ---
        group = QGroupBox("Capacitance")
        form = QFormLayout(group)
        form.addRow("Farads (F):", self.edit_f)
        form.addRow("Microfarads (µF):", self.edit_uf)
        form.addRow("Picofarads (pF):", self.edit_pf)

        root = QVBoxLayout()
        root.addWidget(group)
        root.addWidget(self.status)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)
        self.setFixedWidth(320)

    # ------------------------------------------------------------------
    # Conversion slots
    # ------------------------------------------------------------------

    def _from_farads(self, farads: float):
        if self._updating:
            return
        self._updating = True
        try:
            self.edit_uf.setValue(farads * 1e6)
            self.edit_pf.setValue(farads * 1e12)
            self._set_status(farads, "F")
        finally:
            self._updating = False

    def _from_microfarads(self, uf: float):
        if self._updating:
            return
        self._updating = True
        try:
            self.edit_f.setValue(uf * 1e-6)
            self.edit_pf.setValue(uf * 1e6)
            self._set_status(uf * 1e-6, "F")
        finally:
            self._updating = False

    def _from_picofarads(self, pf: float):
        if self._updating:
            return
        self._updating = True
        try:
            self.edit_f.setValue(pf * 1e-12)
            self.edit_uf.setValue(pf * 1e-6)
            self._set_status(pf * 1e-12, "F")
        finally:
            self._updating = False

    def _set_status(self, farads: float, _unit: str):
        self.status.setText(f"= {farads:.6e} F")


# ----------------------------------------------------------------------
# Standalone usage snippets (not run by main, just for reference)
# ----------------------------------------------------------------------

def _snippet_basic():
    """Minimal standalone use."""
    edit = ScientificLineEdit()
    edit.setValue(1.23e-9)  # Display: "1.230e-09"

    edit.valueChanged.connect(lambda v: print(f"New value: {v}"))

    current = edit.value()  # Returns float


def _snippet_read_write():
    """Typical read/write pattern."""
    edit = ScientificLineEdit()

    # Write
    edit.setValue(0.00047)  # Display: "4.700e-04"
    edit.setValue(42.5)  # Display: "42.500"
    edit.setValue(12_345.0)  # Display: "1.235e+04"

    # Read
    v = edit.value()  # Always a float, regardless of display format
    print(v)


# ----------------------------------------------------------------------

def main():
    app = QApplication(argv=sys.argv)
    window = CapacitanceConverter()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
