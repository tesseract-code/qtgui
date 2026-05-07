from collections import deque

from enum import Enum


class HistoryAction(str, Enum):
    UNDO = "undo"
    REDO = "redo"

class HistoryManager:
    """Manages undo/redo stacks using scene snapshots."""

    def __init__(self, maxlen: int):
        self._undo_stack: deque[dict] = deque(maxlen=maxlen)
        self._redo_stack: deque[dict] = deque(maxlen=maxlen)

    def push(self, snapshot: dict) -> None:
        """Store a snapshot and clear the redo stack."""
        self._undo_stack.append(snapshot)
        self._redo_stack.clear()

    def undo(self, current_snapshot: dict) -> dict | None:
        """Pop from undo stack, push current on redo, return snapshot to restore."""
        if not self._undo_stack:
            return None
        self._redo_stack.append(current_snapshot)
        return self._undo_stack.pop()

    def redo(self, current_snapshot: dict) -> dict | None:
        """Pop from redo stack, push current on undo, return snapshot to restore."""
        if not self._redo_stack:
            return None
        self._undo_stack.append(current_snapshot)
        return self._redo_stack.pop()

    @property
    def undo_stack(self) -> deque:
        return self._undo_stack

    @property
    def redo_stack(self) -> deque:
        return self._redo_stack

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
