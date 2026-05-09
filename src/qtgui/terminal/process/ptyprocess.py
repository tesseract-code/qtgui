from __future__ import annotations

from pycore.platform import IS_WINDOWS

"""
pty_process.py — cross-platform PTY wrapper for Qt applications
===============================================================

Platform       Backend                     Read strategy
-------------- --------------------------- --------------------------------
Linux / macOS  stdlib pty + fcntl          QSocketNotifier (fd is a socket)
Windows        pywinpty (ConPTY / WinPTY)  QThread reader  (no selectable fd)

Dependencies
------------
  All platforms : PyQt6
  Windows only  : pywinpty >= 2.0   (pip install pywinpty)
"""

import os
import signal
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QTimer

from qtgui.terminal.utils import SHELL

# ---------------------------------------------------------------------------
# Platform-specific imports (kept in top-level guards so linters/type-checkers
# on the other platform don't choke on missing modules).
# ---------------------------------------------------------------------------
if IS_WINDOWS:
    from PyQt6.QtCore import QThread

    try:
        from winpty import PtyProcess as _WinPty  # pywinpty >= 2.0
    except ImportError as _exc:
        raise ImportError(
            "pywinpty is required on Windows.\n"
            "Install it with:  pip install pywinpty"
        ) from _exc

    # On Windows we drive the child with cmd.exe (or whatever COMSPEC says).
    # SHELL from utils is typically /bin/sh which is meaningless on Windows.
    _WIN_SHELL: str = os.environ.get("COMSPEC", "cmd.exe")

else:
    import fcntl
    import pty
    import subprocess

    from PyQt6.QtCore import QSocketNotifier
    from qtgui.terminal.utils import _set_winsize

# ===========================================================================
# Windows implementation
# ===========================================================================
if IS_WINDOWS:

    class _ReaderThread(QThread):
        """
        Blocks on PTY reads in a background thread so Qt's event loop is free.

        pywinpty's read() is a blocking call with no selectable fd, so we
        must use a thread rather than QSocketNotifier.
        """

        data_ready = pyqtSignal(bytes)
        eof = pyqtSignal()

        def __init__(self, proc: "_WinPty",
                     parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self._proc = proc

        def run(self) -> None:
            while True:
                try:
                    chunk: str | bytes | None = self._proc.read(4096)
                except Exception:
                    # Process gone or PTY closed.
                    break

                if chunk is None:
                    break

                # pywinpty >= 2 returns str; encode to bytes for pyte et al.
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8", errors="replace")

                if chunk:
                    self.data_ready.emit(chunk)

                if not self._proc.isalive():
                    break

            self.eof.emit()


    # -----------------------------------------------------------------------

    class PtyProcess(QObject):
        """
        Windows PTY process — backed by pywinpty (ConPTY on Win10+, WinPTY
        fallback on older systems).

        Public API is identical to the POSIX version below.
        """

        output_ready = pyqtSignal(bytes)
        finished = pyqtSignal()

        def __init__(self, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self._proc: Optional["_WinPty"] = None
            self._reader: Optional[_ReaderThread] = None
            self._done = False  # guard against double finish

            self._poll = QTimer(self)
            self._poll.setInterval(50)
            self._poll.timeout.connect(self._check_done)

        # --- public ---------------------------------------------------------

        def start(self, cmd: str, cwd: str, cols: int, rows: int) -> None:
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLUMNS"] = str(cols)
            env["LINES"] = str(rows)

            # Spawn via the system shell so shell built-ins, pipes, etc. work.
            full_cmd = f'"{_WIN_SHELL}" /c {cmd}'

            self._proc = _WinPty.spawn(
                full_cmd,
                dimensions=(rows, cols),
                env=env,
                cwd=cwd,
            )

            self._reader = _ReaderThread(self._proc, self)
            self._reader.data_ready.connect(self.output_ready)
            self._reader.eof.connect(self._on_eof)
            self._reader.start()

            self._poll.start()

        def write(self, data: bytes) -> None:
            if self._proc is not None:
                try:
                    # pywinpty >= 2 write() accepts str.
                    self._proc.write(data.decode("utf-8", errors="replace"))
                except Exception:
                    pass

        def resize(self, cols: int, rows: int) -> None:
            if self._proc is not None:
                try:
                    self._proc.setwinsize(rows, cols)
                except Exception:
                    pass

        def kill(self) -> None:
            self._do_cleanup()

        # --- internal -------------------------------------------------------

        def _check_done(self) -> None:
            if self._proc is None or self._proc.isalive():
                return
            # Process exited; the reader thread will emit eof and trigger
            # _on_eof.  Just stop polling here.
            self._poll.stop()

        def _on_eof(self) -> None:
            self._do_cleanup()
            if not self._done:
                self._done = True
                self.finished.emit()

        def _do_cleanup(self) -> None:
            self._poll.stop()

            # Terminate the child process first so the reader thread unblocks.
            if self._proc is not None:
                try:
                    self._proc.terminate(force=True)
                except Exception:
                    pass
                self._proc = None

            # Wait for the reader thread to finish naturally (it will because
            # the process is gone and read() will raise).
            if self._reader is not None:
                if not self._reader.wait(2000):  # 2 s grace period
                    self._reader.terminate()
                    self._reader.wait(500)
                self._reader = None


# ===========================================================================
# POSIX (Linux / macOS) implementation  — original code, unchanged logic
# ===========================================================================
else:

    class PtyProcess(QObject):  # type: ignore[no-redef]
        """
        POSIX PTY process — backed by stdlib pty + fcntl.

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
        finished = pyqtSignal()

        def __init__(self, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self._master_fd: Optional[int] = None
            self._proc: Optional[subprocess.Popen] = None
            self._notifier: Optional[QSocketNotifier] = None

            self._poll = QTimer(self)
            self._poll.setInterval(50)
            self._poll.timeout.connect(self._check_done)

        # --- public ---------------------------------------------------------

        def start(self, cmd: str, cwd: str, cols: int, rows: int) -> None:
            master_fd, slave_fd = pty.openpty()

            # Non-blocking master so the drain loop in _check_done terminates
            # immediately once the buffer is empty rather than hanging.
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            _set_winsize(slave_fd, rows, cols)
            self._master_fd = master_fd

            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLUMNS"] = str(cols)
            env["LINES"] = str(rows)

            self._proc = subprocess.Popen(
                [SHELL, "-c", cmd],
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                close_fds=True,
                cwd=cwd,
                env=env,
                preexec_fn=os.setsid,
            )
            os.close(slave_fd)

            self._notifier = QSocketNotifier(
                master_fd, QSocketNotifier.Type.Read, self
            )
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

        # --- internal -------------------------------------------------------

        def _read_output(self) -> None:
            try:
                data = os.read(self._master_fd, 4096)
                if data:
                    self.output_ready.emit(data)
            except OSError:
                # fd closed / EIO means the slave side hung up.
                self._do_cleanup()
                self.finished.emit()

        def _check_done(self) -> None:
            if self._proc is None or self._proc.poll() is None:
                return

            self._poll.stop()
            if self._notifier:
                self._notifier.setEnabled(False)

            # Drain remaining buffered output.  fd is O_NONBLOCK so this loop
            # exits immediately once the kernel buffer is empty.
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
