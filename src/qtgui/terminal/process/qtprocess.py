from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QProcess

from qtgui.terminal.utils import SHELL, strip_ansi


class TerminalProcess(QObject):
    """
    Thin wrapper around QProcess for non-interactive commands.

    Signals
    -------
    stdout_ready(str)  decoded + ANSI-stripped stdout chunk
    stderr_ready(str)  decoded + ANSI-stripped stderr chunk
    finished()         process has exited
    """

    stdout_ready = pyqtSignal(str)
    stderr_ready = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, cwd: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cwd = cwd
        self._proc = QProcess(self)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(lambda *_: self.finished.emit())

    def run(self, cmd: str) -> None:
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            return
        self._proc.setWorkingDirectory(self._cwd)
        self._proc.start(SHELL, ["-c", cmd])

    def update_cwd(self, path: str) -> None:
        self._cwd = path

    def kill(self) -> None:
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(500)

    def _on_stdout(self) -> None:
        raw = self._proc.readAllStandardOutput().data().decode(errors="replace")
        self.stdout_ready.emit(strip_ansi(raw))

    def _on_stderr(self) -> None:
        raw = self._proc.readAllStandardError().data().decode(errors="replace")
        self.stderr_ready.emit(strip_ansi(raw))
