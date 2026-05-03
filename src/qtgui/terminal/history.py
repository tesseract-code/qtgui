from __future__ import annotations

from pathlib import Path
from typing import Optional


class TerminalHistory:
    """
    Ordered command history with disk persistence.

    push() no longer auto-saves on every call.  The caller (TerminalWidget)
    is responsible for debouncing saves via a QTimer.
    """

    HISTORY_FILE = Path.home() / ".terminal_history"
    MAX_ENTRIES  = 1_000

    def __init__(self) -> None:
        self._entries: list[str] = []
        self._cursor: int = -1
        self._load()

    def _load(self) -> None:
        try:
            if self.HISTORY_FILE.exists():
                lines = self.HISTORY_FILE.read_text(encoding="utf-8").splitlines()
                self._entries = [l for l in lines if l][-self.MAX_ENTRIES:]
        except OSError:
            pass

    def save(self) -> None:
        try:
            text = "\n".join(self._entries[-self.MAX_ENTRIES:])
            self.HISTORY_FILE.write_text(text, encoding="utf-8")
        except OSError:
            pass

    def push(self, cmd: str) -> None:
        """Append cmd, deduplicating consecutive identical entries. Does NOT save."""
        if cmd and (not self._entries or self._entries[-1] != cmd):
            self._entries.append(cmd)
        self._cursor = -1

    def reset_cursor(self) -> None:
        self._cursor = -1

    def older(self) -> Optional[str]:
        if not self._entries:
            return None
        self._cursor = min(self._cursor + 1, len(self._entries) - 1)
        return self._at_cursor()

    def newer(self) -> Optional[str]:
        self._cursor = max(self._cursor - 1, -1)
        return self._at_cursor() if self._cursor >= 0 else ""

    def _at_cursor(self) -> str:
        return self._entries[-(self._cursor + 1)]
