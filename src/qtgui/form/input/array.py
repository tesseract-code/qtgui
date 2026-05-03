from typing import Any, Tuple, Type, List

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHBoxLayout,
    QSpinBox,
    QLabel
)

from qtgui.form.input.base import BaseInputWidget, ValidationResult


class ArrayInputWidget(BaseInputWidget):
    """Widget for 1D or 2D array input using a table."""

    def __init__(self, param_name: str, type_info: Any,
                 shape: Tuple[int, ...] = None,
                 element_type: Type = float,
                 parent: QWidget = None):
        self.shape = shape or (3, 3)  # Default to 3x3
        self.element_type = element_type
        self.is_1d = len(self.shape) == 1
        super().__init__(param_name, type_info, parent)

    def _build_widget(self) -> None:
        container = QWidget(self.parent)
        layout = QVBoxLayout(container)

        # Create table
        if self.is_1d:
            rows, cols = 1, self.shape[0]
        else:
            rows, cols = self.shape[0], self.shape[1]

        self._table = QTableWidget(rows, cols)
        self._table.setMaximumHeight(200)

        # Initialize cells with default values
        for i in range(rows):
            for j in range(cols):
                item = QTableWidgetItem("0")
                self._table.setItem(i, j, item)

        layout.addWidget(self._table)

        # Add resize buttons
        button_layout = QHBoxLayout()
        self._rows_spin = QSpinBox()
        self._rows_spin.setMinimum(1)
        self._rows_spin.setMaximum(100)
        self._rows_spin.setValue(rows)
        self._rows_spin.valueChanged.connect(self._resize_table)

        self._cols_spin = QSpinBox()
        self._cols_spin.setMinimum(1)
        self._cols_spin.setMaximum(100)
        self._cols_spin.setValue(cols)
        self._cols_spin.valueChanged.connect(self._resize_table)

        button_layout.addWidget(QLabel("Rows:"))
        button_layout.addWidget(self._rows_spin)
        button_layout.addWidget(QLabel("Cols:"))
        button_layout.addWidget(self._cols_spin)
        button_layout.addStretch()

        layout.addLayout(button_layout)

        self._widget = container

    def _resize_table(self) -> None:
        """Resize the table based on spinbox values."""
        rows = self._rows_spin.value()
        cols = self._cols_spin.value()
        self._table.setRowCount(rows)
        self._table.setColumnCount(cols)

        # Initialize new cells
        for i in range(rows):
            for j in range(cols):
                if not self._table.item(i, j):
                    self._table.setItem(i, j, QTableWidgetItem("0"))

    def get_value(self) -> List:
        """Get the array values from the table."""
        rows = self._table.rowCount()
        cols = self._table.columnCount()

        if self.is_1d:
            return [self._parse_cell(0, j) for j in range(cols)]
        else:
            return [[self._parse_cell(i, j) for j in range(cols)]
                    for i in range(rows)]

    def _parse_cell(self, row: int, col: int) -> Any:
        """Parse a cell value to the correct type."""
        item = self._table.item(row, col)
        text = item.text() if item else "0"

        try:
            if self.element_type == int:
                return int(float(text))  # Handle "1.0" -> 1
            elif self.element_type == float:
                return float(text)
            else:
                return self.element_type(text)
        except ValueError:
            return self.element_type()  # Default value

    def set_value(self, value: List) -> None:
        """Set the array values in the table."""
        if not value:
            return

        if self.is_1d:
            self._table.setColumnCount(len(value))
            for j, val in enumerate(value):
                self._table.setItem(0, j, QTableWidgetItem(str(val)))
        else:
            self._table.setRowCount(len(value))
            self._table.setColumnCount(len(value[0]) if value else 0)
            for i, row in enumerate(value):
                for j, val in enumerate(row):
                    self._table.setItem(i, j, QTableWidgetItem(str(val)))

    def validate(self) -> ValidationResult:
        """Validate all cells contain valid values."""
        try:
            value = self.get_value()
            return ValidationResult(True, value)
        except Exception as e:
            return ValidationResult(False, None, f"Invalid array data: {e}")
