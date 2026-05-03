"""
PyQt6 Table-Based Logging Widget with filtering and export capabilities.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QIcon, QPixmap

from pycore.log.constants import DEFAULT_LOG_LEVEL
from qtgui.edit import SearchLineEdit
from qtgui.log.badge import LogLevelBadge
from qtgui.log.constants import MAX_LOG_LINES, DEFAULT_FONT_SIZE, BADGE_HEIGHT
from qtgui.log.model import LogTableModel, LogFilterProxyModel, LogColumns
from qtgui.log.record import LogRecordHandler
from qtgui.pixmap import colorize_pixmap


class LogWidget(QtWidgets.QWidget):
    """
    Main log viewer widget integrating model, view, and controller logic.

    This widget coordinates between:
    - LogRecordHandler: Integration with Python logging
    - LogTableModel: Data storage
    - LogFilterProxyModel: Filtering logic
    - UI Components: Presentation
    """

    got_message = QtCore.pyqtSignal()
    got_serious_message = QtCore.pyqtSignal()

    def __init__(
            self,
            parent: Optional[QtWidgets.QWidget] = None,
            max_lines: int = MAX_LOG_LINES,
            font_size: int = DEFAULT_FONT_SIZE
    ) -> None:
        """
        Initialize the log widget.

        Args:
            parent: Parent widget
            max_lines: Maximum number of log lines to retain
            font_size: Font size for log display
        """
        super().__init__(parent=parent)

        self._max_lines = max_lines
        self._auto_scroll_enabled = True

        # Level counters (using logging module levels)
        self._level_counts = {
            logging.DEBUG: 0,
            logging.INFO: 0,
            logging.WARNING: 0,
            logging.ERROR: 0,
            logging.CRITICAL: 0
        }

        # Create MVC components
        self._setup_models()
        self._setup_handler()
        self._setup_ui(font_size)

        # Initialize state
        self._update_level_badges()
        self._update_items_label()

    def _setup_models(self) -> None:
        """Initialize the data model and proxy model."""
        self._table_model = LogTableModel(max_rows=self._max_lines)
        self._proxy_model = LogFilterProxyModel()
        self._proxy_model.setSourceModel(self._table_model)

    def _setup_handler(self) -> None:
        """Initialize the logging handler and connect signals."""
        self._handler = LogRecordHandler(level=DEFAULT_LOG_LEVEL)
        self._handler.set_callback(self._on_log_record_received)

    def _setup_ui(self, font_size: int) -> None:
        """
        Create the user interface.

        Args:
            font_size: Font size for the table
        """
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        layout.setSpacing(0)

        # Top bar with badges and controls
        layout.addWidget(self._create_top_bar())
        layout.addSpacing(10)

        # Table view
        self._table_view = self._create_table_view(font_size)
        layout.addWidget(self._table_view)
        layout.addSpacing(2)

        # Bottom toolbar
        layout.addWidget(self._create_toolbar())

    def _create_top_bar(self) -> QtWidgets.QWidget:
        """
        Create the top bar with level badges.

        Returns:
            The top bar widget
        """
        top_widget = QtWidgets.QWidget()
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_widget.setLayout(top_layout)

        # Create badges for main log levels
        self._badges = {}
        for level in [logging.DEBUG, logging.INFO, logging.WARNING,
                      logging.ERROR, logging.CRITICAL]:
            badge = LogLevelBadge(level)
            badge.clicked.connect(lambda l=level: self._filter_by_level(l))
            self._badges[level] = badge
            top_layout.addWidget(badge)

        top_layout.addStretch()

        top_layout.addLayout(self._create_search_bar())

        return top_widget

    def _create_search_bar(self) -> QtWidgets.QHBoxLayout:
        """
        Create the search bar.

        Returns:
            The search bar layout
        """
        search_layout = QtWidgets.QHBoxLayout()

        # Search input
        self._search_input = SearchLineEdit(
            placeholder="Search...", parent=self)
        self._search_input.setToolTip("Search table entries. RegEx allowed")
        self._search_input.setMinimumHeight(BADGE_HEIGHT)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self._search_input)

        return search_layout

    def _create_table_view(self, font_size: int) -> QtWidgets.QTableView:
        """
        Create and configure the table view.

        Args:
            font_size: Font size for the table

        Returns:
            The configured table view
        """
        table_view = QtWidgets.QTableView()
        table_view.setModel(self._proxy_model)
        table_view.setSortingEnabled(True)
        table_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        table_view.setAlternatingRowColors(True)
        table_view.verticalHeader().setVisible(False)
        table_view.setWordWrap(False)

        # Enable context menu for copying
        table_view.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        table_view.customContextMenuRequested.connect(self._show_context_menu)

        # Set font
        font = QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(font_size)
        table_view.setFont(font)

        # Configure column widths
        header = table_view.horizontalHeader()
        header.setSectionResizeMode(LogColumns.LEVEL,
                                    QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(LogColumns.TIME,
                                    QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(LogColumns.LOGGER,
                                    QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(LogColumns.MESSAGE,
                                    QtWidgets.QHeaderView.ResizeMode.Stretch)

        return table_view

    def _create_toolbar(self) -> QtWidgets.QToolBar:
        """
        Create the bottom toolbar.

        Returns:
            The toolbar widget
        """
        toolbar = QtWidgets.QToolBar()

        # Log level selector
        # toolbar.addWidget(QtWidgets.QLabel("Log Level:"))

        self._level_selector = QtWidgets.QComboBox()
        # Use logging module's level constants directly
        self._level_selector.addItem(logging.getLevelName(logging.DEBUG),
                                     logging.DEBUG)
        self._level_selector.addItem(logging.getLevelName(logging.INFO),
                                     logging.INFO)
        self._level_selector.addItem(logging.getLevelName(logging.WARNING),
                                     logging.WARNING)
        self._level_selector.addItem(logging.getLevelName(logging.ERROR),
                                     logging.ERROR)
        self._level_selector.addItem(logging.getLevelName(logging.CRITICAL),
                                     logging.CRITICAL)
        # Default to
        # INFO
        self._level_selector.currentIndexChanged.connect(self._on_level_changed)
        toolbar.addWidget(self._level_selector)

        toolbar.addSeparator()

        # Items per page info
        self._items_label = QtWidgets.QLabel()
        self._items_label.setStyleSheet('font-weight: bold;')
        toolbar.addWidget(self._items_label)

        # Spacer
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Preferred
        )
        toolbar.addWidget(spacer)

        # Auto-scroll checkbox
        self._auto_scroll_check = QtWidgets.QCheckBox("Auto-scroll")
        self._auto_scroll_check.setChecked(True)
        self._auto_scroll_check.toggled.connect(self._set_auto_scroll)
        toolbar.addWidget(self._auto_scroll_check)

        toolbar.addSeparator()

        # Export button
        export_btn = QtWidgets.QToolButton()
        export_btn.setIcon(
            QIcon(
                colorize_pixmap(
                    QPixmap("line-icons:export-line.svg"),
                    color=QColor(self.palette().buttonText().color()))
            ))
        export_btn.setStyleSheet("border-radius: 4px;")
        export_btn.setText("Export logs")
        export_btn.setIconSize(toolbar.iconSize())
        export_btn.clicked.connect(self._export_logs)
        toolbar.addWidget(export_btn)

        toolbar.addSeparator()

        # Clear button
        clear_btn = QtWidgets.QToolButton()
        clear_btn.setIcon(
            QIcon(
                colorize_pixmap(
                    QPixmap("line-icons:delete-bin-line.svg"),
                    color=QColor(self.palette().buttonText().color()))
            ))
        clear_btn.setStyleSheet("border-radius: 4px;")
        clear_btn.clicked.connect(self._clear_logs)
        toolbar.addWidget(clear_btn)

        self._level_selector.setCurrentIndex(1)

        return toolbar

    # ========================================================================
    # Controller Logic
    # ========================================================================

    @QtCore.pyqtSlot(logging.LogRecord)
    def _on_log_record_received(self, record: logging.LogRecord) -> None:
        """
        Handle incoming log record from the handler.

        Args:
            record: The log record to process
        """
        try:
            # Add to model
            self._table_model.add_record(record)

            # Update counters
            if record.levelno in self._level_counts:
                self._level_counts[record.levelno] += 1
            elif record.levelno == logging.CRITICAL:
                self._level_counts[logging.CRITICAL] += 1

            self._update_level_badges()
            self._update_items_label()

            # Auto-scroll
            if self._auto_scroll_enabled:
                self._scroll_to_bottom()

            # Emit signals
            self.got_message.emit()
            if record.levelno >= logging.WARNING:
                self.got_serious_message.emit()

        except Exception as e:
            print(f"Error handling log record: {e}", file=sys.stderr)

    def _filter_by_level(self, level: int) -> None:
        """
        Filter table to show only the specified log level and above.

        Args:
            level: The log level to filter by
        """
        # Find the index in the combo box
        for i in range(self._level_selector.count()):
            if self._level_selector.itemData(i) == level:
                self._level_selector.setCurrentIndex(i)
                break

    def _on_level_changed(self, index: int) -> None:
        """
        Handle log level selection change.

        Args:
            index: The selected combobox index
        """
        level = self._level_selector.itemData(index)
        # Update both handler and proxy model to ensure all debug messages are captured
        self._handler.setLevel(level)
        self._proxy_model.set_min_log_level(level)
        self._update_items_label()

    def _on_search_changed(self, text: str) -> None:
        """
        Handle search text changes.

        Args:
            text: The search text
        """
        import re
        # Check if text looks like regex (contains special chars)
        pattern = text
        if text and not re.search(r'[.*+?^${}()|[\]\\]', text):
            # Not regex, escape it
            pattern = re.escape(text)

        self._proxy_model.set_search_pattern(pattern)
        self._update_items_label()

    def _set_auto_scroll(self, enabled: bool) -> None:
        """
        Enable or disable auto-scroll.

        Args:
            enabled: Whether auto-scroll should be enabled
        """
        self._auto_scroll_enabled = enabled

    def _scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the table."""
        if self._proxy_model.rowCount() > 0:
            last_row = self._proxy_model.rowCount() - 1
            last_index = self._proxy_model.index(last_row, 0)
            self._table_view.scrollTo(last_index)

    def _clear_logs(self) -> None:
        """Clear all logs from the table."""
        self._table_model.clear()
        self._level_counts = {level: 0 for level in self._level_counts}
        self._update_level_badges()
        self._update_items_label()

    def _update_level_badges(self) -> None:
        """Update the count displays on all badges."""
        for level, badge in self._badges.items():
            badge.set_count(self._level_counts.get(level, 0))

    def _update_items_label(self) -> None:
        """Update the items count label."""
        visible = self._proxy_model.rowCount()
        total = self._table_model.rowCount()
        if visible == total:
            self._items_label.setText(f"{total} items")
        else:
            self._items_label.setText(f"{visible} of {total} items")

    def _export_logs(self) -> None:
        """Export current log contents to a file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"logs_{timestamp}.txt"

        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Logs",
            default_filename,
            "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
        )

        if not filename:
            return

        try:
            path = Path(filename)

            # Export visible (filtered) rows
            lines = []
            for row in range(self._proxy_model.rowCount()):
                # Get data from proxy model
                indices = [
                    self._proxy_model.index(row, col)
                    for col in range(self._proxy_model.columnCount())
                ]

                values = [
                    self._proxy_model.data(idx,
                                           QtCore.Qt.ItemDataRole.DisplayRole)
                    for idx in indices
                ]

                if filename.endswith('.csv'):
                    # CSV format
                    escaped = [f'"{v}"' if v else '""' for v in values]
                    lines.append(",".join(escaped))
                else:
                    # Text format
                    level, time, logger, message = values
                    lines.append(f"{time} - {logger} - {level}\n{message}")

            if filename.endswith('.csv'):
                content = ",".join(LogTableModel.HEADERS) + "\n" + "\n".join(
                    lines)
            else:
                content = "\n\n".join(lines)

            path.write_text(content, encoding='utf-8')

            QtWidgets.QMessageBox.information(
                self,
                "Export Successful",
                f"Logs exported to:\n{filename}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export logs:\n{str(e)}"
            )

    def _show_context_menu(self, position: QtCore.QPoint) -> None:
        """
        Show context menu for copying log entries.

        Args:
            position: The position where the menu was requested
        """
        # Get the index at the clicked position
        index = self._table_view.indexAt(position)

        # Get selected rows
        selection = self._table_view.selectionModel()
        selected_rows = selection.selectedRows()

        # Create context menu
        menu = QtWidgets.QMenu(self)

        if index.isValid():
            # Copy cell action
            copy_cell_action = menu.addAction("Copy Cell")
            copy_cell_action.triggered.connect(lambda: self._copy_cell(index))

            # Copy message action (for the full message from the record)
            if index.column() == LogColumns.MESSAGE or selected_rows:
                copy_message_action = menu.addAction("Copy Full Message")
                copy_message_action.triggered.connect(
                    lambda: self._copy_full_message(index))

            menu.addSeparator()

        if selected_rows:
            # Copy row action
            copy_row_action = menu.addAction(
                f"Copy Row{'s' if len(selected_rows) > 1 else ''}")
            copy_row_action.triggered.connect(self._copy_selected_rows)

            # Copy row with exception info
            copy_full_row_action = menu.addAction(
                f"Copy Full Row{'s' if len(selected_rows) > 1 else ''} (with exceptions)")
            copy_full_row_action.triggered.connect(
                lambda: self._copy_selected_rows(include_exceptions=True))

            menu.addSeparator()

        # Copy all visible logs
        copy_all_action = menu.addAction("Copy All Visible Logs")
        copy_all_action.triggered.connect(self._copy_all_visible)

        # Show the menu at the cursor position
        menu.exec(self._table_view.viewport().mapToGlobal(position))

    def _copy_cell(self, index: QtCore.QModelIndex) -> None:
        """
        Copy a single cell to clipboard.

        Args:
            index: The model index of the cell to copy
        """
        if not index.isValid():
            return

        text = self._proxy_model.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
        if text:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(str(text))

    def _copy_full_message(self, index: QtCore.QModelIndex) -> None:
        """
        Copy the full message from the log record, including exception info if present.

        Args:
            index: The model index (any column in the row)
        """
        if not index.isValid():
            return

        # Get the message column index for this row
        msg_index = self._proxy_model.index(index.row(), LogColumns.MESSAGE)

        # Get the log record
        record = self._proxy_model.data(msg_index,
                                        QtCore.Qt.ItemDataRole.UserRole)

        if record:
            message = record.getMessage()

            # Add exception info if present
            if record.exc_info:
                import traceback
                message += "\n\n" + "".join(
                    traceback.format_exception(*record.exc_info))

            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(message)

    def _copy_selected_rows(self, include_exceptions: bool = False) -> None:
        """
        Copy selected rows to clipboard.

        Args:
            include_exceptions: Whether to include exception tracebacks
        """
        selection = self._table_view.selectionModel()
        selected_rows = selection.selectedRows()

        if not selected_rows:
            return

        lines = []
        for row_index in selected_rows:
            row = row_index.row()

            # Get all column data
            level_idx = self._proxy_model.index(row, LogColumns.LEVEL)
            time_idx = self._proxy_model.index(row, LogColumns.TIME)
            logger_idx = self._proxy_model.index(row, LogColumns.LOGGER)
            msg_idx = self._proxy_model.index(row, LogColumns.MESSAGE)

            level = self._proxy_model.data(level_idx,
                                           QtCore.Qt.ItemDataRole.DisplayRole)
            time = self._proxy_model.data(time_idx,
                                          QtCore.Qt.ItemDataRole.DisplayRole)
            logger = self._proxy_model.data(logger_idx,
                                            QtCore.Qt.ItemDataRole.DisplayRole)
            message = self._proxy_model.data(msg_idx,
                                             QtCore.Qt.ItemDataRole.DisplayRole)

            row_text = f"{time} - {logger} - {level}\n{message}"

            # Add exception info if requested
            if include_exceptions:
                record = self._proxy_model.data(msg_idx,
                                                QtCore.Qt.ItemDataRole.UserRole)
                if record and record.exc_info:
                    import traceback
                    row_text += "\n" + "".join(
                        traceback.format_exception(*record.exc_info))

            lines.append(row_text)

        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText("\n\n".join(lines))

    def _copy_all_visible(self) -> None:
        """Copy all visible (filtered) logs to clipboard."""
        lines = []
        for row in range(self._proxy_model.rowCount()):
            level_idx = self._proxy_model.index(row, LogColumns.LEVEL)
            time_idx = self._proxy_model.index(row, LogColumns.TIME)
            logger_idx = self._proxy_model.index(row, LogColumns.LOGGER)
            msg_idx = self._proxy_model.index(row, LogColumns.MESSAGE)

            level = self._proxy_model.data(level_idx,
                                           QtCore.Qt.ItemDataRole.DisplayRole)
            time = self._proxy_model.data(time_idx,
                                          QtCore.Qt.ItemDataRole.DisplayRole)
            logger = self._proxy_model.data(logger_idx,
                                            QtCore.Qt.ItemDataRole.DisplayRole)
            message = self._proxy_model.data(msg_idx,
                                             QtCore.Qt.ItemDataRole.DisplayRole)

            lines.append(f"{time} - {logger} - {level}\n{message}")

        if lines:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText("\n\n".join(lines))

    # ========================================================================
    # Public API
    # ========================================================================

    def get_handler(self) -> LogRecordHandler:
        """
        Get the logging handler instance.

        Returns:
            The log record handler attached to this viewer
        """
        return self._handler

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """
        Handle widget close event and clean up resources.

        Args:
            event: The close event
        """
        try:
            self._handler.teardown()
        except Exception as e:
            print(f"Error during widget cleanup: {e}", file=sys.stderr)
        super().closeEvent(event)
