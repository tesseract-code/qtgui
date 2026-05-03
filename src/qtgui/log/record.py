import logging
import sys
from typing import List, Optional, Callable

from PyQt6 import QtCore


class LogRecordHandler(logging.Handler):
    """
    Custom logging handler that queues log records for thread-safe UI updates.

    This handler bridges Python's logging system with Qt's UI thread using
    a queue-based approach instead of signals, preventing interference with
    logging system cleanup and flushing.
    """

    def __init__(self, level: int = logging.NOTSET) -> None:
        """
        Initialize the log record handler.

        Args:
            level: Minimum log level to process
        """
        super().__init__(level=level)
        self._record_queue: List[logging.LogRecord] = []
        self._queue_lock = QtCore.QMutex()
        self._callback: Optional[Callable[[logging.LogRecord], None]] = None
        self._timer: Optional[QtCore.QTimer] = None

    def set_callback(self,
                     callback: Callable[[logging.LogRecord], None]) -> None:
        """
        Set the callback function to be called with log records.

        This should be called from the main Qt thread.

        Args:
            callback: Function to call with each log record
        """
        self._callback = callback

        # Set up a timer to process queued records from the main thread
        if self._timer is None:
            self._timer = QtCore.QTimer()
            self._timer.timeout.connect(self._process_queue)
            self._timer.start(100)  # Process queue every 100ms

    def emit(self, record: logging.LogRecord) -> None:
        """
        Queue a log record for processing in the main thread.

        Args:
            record: The log record to process
        """
        try:
            # Thread-safe queue operation
            self._queue_lock.lock()
            try:
                self._record_queue.append(record)
            finally:
                self._queue_lock.unlock()
        except Exception as e:
            # Don't let logging errors crash the application
            print(f"Error in logging handler: {e}", file=sys.stderr)

    def _process_queue(self) -> None:
        """Process all queued log records (called from main thread via timer)."""
        if not self._callback:
            return

        # Get all pending records
        self._queue_lock.lock()
        try:
            records = self._record_queue.copy()
            self._record_queue.clear()
        finally:
            self._queue_lock.unlock()

        # Process records in main thread
        for record in records:
            try:
                self._callback(record)
            except Exception as e:
                print(f"Error processing log record: {e}", file=sys.stderr)

    def flush(self) -> None:
        """Flush any pending log records."""
        # Process remaining records immediately
        self._process_queue()
        super().flush()

    def teardown(self) -> None:
        """Clean up the handler and remove it from the logging system."""
        try:
            # Stop the timer
            if self._timer:
                self._timer.stop()
                self._timer = None

            # Flush remaining records
            self.flush()

            # Clear callback
            self._callback = None

            # Remove from logging system
            logging.root.removeHandler(self)

            self.close()
        except Exception as e:
            print(f"Error during handler teardown: {e}", file=sys.stderr)
