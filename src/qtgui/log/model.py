import logging
from datetime import datetime
from enum import IntEnum
from typing import Optional, List

from PyQt6 import QtCore, QtGui
from PyQt6.QtGui import QColor, QIcon, QPixmap

from qtgui.log.constants import MAX_LOG_LINES, LOG_LEVEL_COLORS, LOG_LEVEL_ICONS
from qtgui.pixmap import colorize_pixmap


class LogColumns(IntEnum):
    """Enum for log table columns."""
    LEVEL = 0
    TIME = 1
    LOGGER = 2
    MESSAGE = 3


class LogTableModel(QtCore.QAbstractTableModel):
    """
    Table model for storing and displaying log records.

    This model uses Python's logging.LogRecord objects directly without
    duplication, maintaining a clean separation between data and presentation.
    """

    HEADERS = ["Level", "Time", "Logger", "Message"]

    def __init__(
            self,
            parent: Optional[QtCore.QObject] = None,
            max_rows: int = MAX_LOG_LINES
    ) -> None:
        """
        Initialize the log table model.

        Args:
            parent: Parent QObject
            max_rows: Maximum number of rows to keep in memory
        """
        super().__init__(parent)
        self._log_records: List[logging.LogRecord] = []
        self._max_rows = max_rows

    def rowCount(self,
                 parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        """Return the number of rows in the model."""
        if parent.isValid():
            return 0
        return len(self._log_records)

    def columnCount(self,
                    parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        """Return the number of columns in the model."""
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def data(self, index: QtCore.QModelIndex,
             role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        """
        Return data for the given index and role.

        Args:
            index: The model index
            role: The data role

        Returns:
            The data for the specified role
        """
        if not index.isValid() or index.row() >= len(self._log_records):
            return None

        record = self._log_records[index.row()]
        column = index.column()

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if column == LogColumns.LEVEL:
                # Use logging module's getLevelName
                return logging.getLevelName(record.levelno)
            elif column == LogColumns.TIME:
                dt = datetime.fromtimestamp(record.created)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            elif column == LogColumns.LOGGER:
                return record.name
            elif column == LogColumns.MESSAGE:
                return record.getMessage()

        elif role == QtCore.Qt.ItemDataRole.ForegroundRole:
            if column == LogColumns.LEVEL:
                return QtGui.QColor(
                    LOG_LEVEL_COLORS.get(record.levelno, "#000000"))

        elif role == QtCore.Qt.ItemDataRole.DecorationRole:
            if column == LogColumns.LEVEL:
                icon_path = LOG_LEVEL_ICONS.get(record.levelno)
                if icon_path:
                    color = QColor(
                        LOG_LEVEL_COLORS.get(record.levelno))
                    return QIcon(
                        colorize_pixmap(
                            QPixmap(icon_path), color=color
                        )
                    )

        elif role == QtCore.Qt.ItemDataRole.FontRole:
            if column == LogColumns.LEVEL:
                font = QtGui.QFont()
                font.setBold(True)
                return font

        elif role == QtCore.Qt.ItemDataRole.ToolTipRole:
            if column == LogColumns.MESSAGE:
                # Show full message and exception info in tooltip
                tooltip = record.getMessage()
                if record.exc_info:
                    import traceback
                    tooltip += "\n\n" + "".join(
                        traceback.format_exception(*record.exc_info))
                return tooltip

        elif role == QtCore.Qt.ItemDataRole.UserRole:
            # Store the full LogRecord for filtering and other uses
            return record

        return None

    def headerData(
            self,
            section: int,
            orientation: QtCore.Qt.Orientation,
            role: int = QtCore.Qt.ItemDataRole.DisplayRole
    ):
        """
        Return header data for the given section.

        Args:
            section: The header section (column or row number)
            orientation: Horizontal or vertical orientation
            role: The data role

        Returns:
            The header data
        """
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return self.HEADERS[section]
        return None

    def add_record(self, record: logging.LogRecord) -> None:
        """
        Add a new log record to the model.

        Args:
            record: The log record to add
        """
        # Remove oldest records if we exceed max_rows
        if len(self._log_records) >= self._max_rows:
            self.beginRemoveRows(QtCore.QModelIndex(), 0, 0)
            self._log_records.pop(0)
            self.endRemoveRows()

        # Add new record
        row = len(self._log_records)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._log_records.append(record)
        self.endInsertRows()

    def clear(self) -> None:
        """Clear all log records from the model."""
        if self._log_records:
            self.beginResetModel()
            self._log_records.clear()
            self.endResetModel()

    def get_record(self, row: int) -> Optional[logging.LogRecord]:
        """
        Get the log record at the specified row.

        Args:
            row: The row index

        Returns:
            The log record or None if row is invalid
        """
        if 0 <= row < len(self._log_records):
            return self._log_records[row]
        return None


class LogFilterProxyModel(QtCore.QSortFilterProxyModel):
    """
    Proxy model for filtering log records by level and search text.

    Uses the logging module's level system directly without duplication.
    """

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        """
        Initialize the filter proxy model.

        Args:
            parent: Parent QObject
        """
        super().__init__(parent)
        self._search_pattern: Optional[str] = None
        self._min_log_level: int = logging.NOTSET

    def set_search_pattern(self, pattern: str) -> None:
        """
        Set the search filter pattern.

        Args:
            pattern: Regular expression pattern to search for (empty string to clear)
        """
        if pattern:
            self._search_pattern = pattern
        else:
            self._search_pattern = None
        self.invalidateFilter()

    def set_min_log_level(self, level: int) -> None:
        """
        Set the minimum log level to display.

        Args:
            level: The minimum log level (use logging.DEBUG, logging.INFO, etc.)
        """
        self._min_log_level = level
        self.invalidateFilter()

    def filterAcceptsRow(
            self,
            source_row: int,
            source_parent: QtCore.QModelIndex
    ) -> bool:
        """
        Determine if a row should be shown based on filters.

        Args:
            source_row: The row number in the source model
            source_parent: The parent index in the source model

        Returns:
            True if the row should be shown, False otherwise
        """
        source_model = self.sourceModel()
        if not isinstance(source_model, LogTableModel):
            return True

        # Get the log record directly from the model
        record = source_model.get_record(source_row)
        if not record:
            return True

        # Filter by log level using logging module's level system
        if record.levelno < self._min_log_level:
            return False

        # Filter by search pattern
        if self._search_pattern:
            try:
                import re
                # Search in message, logger name, and level name
                searchable_text = (
                    f"{record.getMessage()} "
                    f"{record.name} "
                    f"{logging.getLevelName(record.levelno)}"
                )
                if not re.search(self._search_pattern, searchable_text,
                                 re.IGNORECASE):
                    return False
            except re.error:
                # Invalid regex, don't filter
                pass

        return True
