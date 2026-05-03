from __future__ import annotations

import fcntl
import os
import pty
import signal
import subprocess
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QSocketNotifier, QTimer

from qtgui.terminal.utils import _set_winsize, SHELL


class PtyProcess(QObject):
    """
    Runs a command inside a real PTY so ncurses / TUI programs work.

    Fixes vs original
    -----------------
    * master fd is set O_NONBLOCK after openpty() so the drain loop in
      _check_done cannot stall the event loop waiting for EOF.
    * _do_cleanup is idempotent; calling kill() twice is harmless.

    Signals
    -------
    output_ready(bytes)  raw PTY output — caller feeds this into pyte
    finished()           process has exited and remaining output drained
    """

    output_ready = pyqtSignal(bytes)
    finished     = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._master_fd: Optional[int] = None
        self._proc: Optional[subprocess.Popen] = None
        self._notifier: Optional[QSocketNotifier] = None
        self._poll = QTimer(self)
        self._poll.setInterval(50)
        self._poll.timeout.connect(self._check_done)

    # --- public ---

    def start(self, cmd: str, cwd: str, cols: int, rows: int) -> None:
        master_fd, slave_fd = pty.openpty()

        # Make the master fd non-blocking so os.read() in the drain loop
        # raises BlockingIOError (OSError) instead of hanging.
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        _set_winsize(slave_fd, rows, cols)
        self._master_fd = master_fd

        env = os.environ.copy()
        env["TERM"]    = "xterm-256color"
        env["COLUMNS"] = str(cols)
        env["LINES"]   = str(rows)

        self._proc = subprocess.Popen(
            [SHELL, "-c", cmd],
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            close_fds=True,
            cwd=cwd,
            env=env,
            preexec_fn=os.setsid,
        )
        os.close(slave_fd)

        self._notifier = QSocketNotifier(master_fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._read_output)
        self._poll.start()

    def write(self, data: bytes) -> None:
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError:
                pass

    def resize(self, cols: int, rows: int) -> None:
        if self._master_fd is not None:
            try:
                _set_winsize(self._master_fd, rows, cols)
            except OSError:
                pass

    def kill(self) -> None:
        self._do_cleanup()

    # --- internal ---

    def _read_output(self) -> None:
        try:
            data = os.read(self._master_fd, 4096)
            if data:
                self.output_ready.emit(data)
        except OSError:
            self._do_cleanup()
            self.finished.emit()

    def _check_done(self) -> None:
        if self._proc is None or self._proc.poll() is None:
            return
        self._poll.stop()
        if self._notifier:
            self._notifier.setEnabled(False)
        # Drain remaining data.  fd is O_NONBLOCK so this loop terminates
        # immediately once the buffer is empty rather than blocking.
        try:
            while True:
                data = os.read(self._master_fd, 4096)
                if not data:
                    break
                self.output_ready.emit(data)
        except OSError:
            pass
        self._do_cleanup()
        self.finished.emit()

    def _do_cleanup(self) -> None:
        self._poll.stop()
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
