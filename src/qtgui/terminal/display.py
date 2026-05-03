from __future__ import annotations

import os
import sys
from html import escape

import pyte
from PyQt6.QtGui import QTextCharFormat, QFont, QColor, QTextCursor
from PyQt6.QtWidgets import QTextEdit

from qtgui.terminal.utils import _pyte_color


class Palette:
    BG     = "#121212"
    FG     = "#E0E0E0"
    PROMPT = "#00FF7F"   # Spring Green
    PATH   = "#6495ED"   # Cornflower Blue
    ERROR  = "#FF6B6B"   # Soft Red
    WARN   = "#FFD700"   # Gold



class TerminalDisplay(QTextEdit):
    """
    All visual concerns live here: prompt drawing, colored output,
    pyte screen rendering, and the prompt-boundary write guard.

    There is no process management, history, or command execution here.
    TerminalWidget installs an event filter to intercept keystrokes so
    this class stays focused purely on rendering.
    """

    def __init__(self) -> None:
        super().__init__()
        self._prompt_end: int = 0
        # Cache QTextCharFormat by (fg_hex, bg_hex, bold) to avoid allocating
        # up to 1 920 objects per pyte screen refresh.
        self._fmt_cache: dict[tuple[str, str, bool], QTextCharFormat] = {}
        self._setup_appearance()

    def _setup_appearance(self) -> None:
        family = "Menlo" if sys.platform == "darwin" else "Cascadia Code, Consolas"
        self.setFont(QFont(family, 12))
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Palette.BG};
                color: {Palette.FG};
                border: none;
            }}
        """)
        self.setUndoRedoEnabled(False)

    # --- prompt ---

    def render_prompt(self, cwd: str) -> None:
        home = os.path.expanduser("~")
        display_path = escape(cwd.replace(home, "~"))
        self._goto_end()
        self.insertHtml(
            f"<br>"
            f"<b style='color:{Palette.PROMPT};'>➜ </b>"
            f"<b style='color:{Palette.PATH};'>{display_path}</b>"
            f"<span style='color:{Palette.FG};'> % </span>"
        )
        self._goto_end()
        self._prompt_end = self.textCursor().position()
        self.ensureCursorVisible()

    # --- normal output ---

    def append_output(self, text: str, color: str = Palette.FG) -> None:
        self._goto_end()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self.textCursor()
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # --- PTY / TUI screen rendering ---

    def _get_fmt(self, fg: str, bg: str, bold: bool) -> QTextCharFormat:
        """Return a cached QTextCharFormat for the given visual attributes."""
        key = (fg, bg, bold)
        fmt = self._fmt_cache.get(key)
        if fmt is None:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(fg))
            if bg.lower() != Palette.BG.lower():
                fmt.setBackground(QColor(bg))
            if bold:
                fmt.setFontWeight(700)
            self._fmt_cache[key] = fmt
        return fmt

    def render_pty_screen(self, screen: "pyte.Screen", start_pos: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(start_pos)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()

        default_fmt = self._get_fmt(Palette.FG, Palette.BG, False)

        for y in range(screen.lines):
            row = screen.buffer[y]
            x = 0
            while x < screen.columns:
                char = row[x]
                fg   = _pyte_color(char.fg, default=Palette.FG)
                bg   = _pyte_color(char.bg, default=Palette.BG)
                bold = getattr(char, "bold", False)

                # Batch consecutive characters sharing the same format
                batch = char.data or " "
                while x + len(batch) < screen.columns:
                    nxt = row[x + len(batch)]
                    if (nxt.fg == char.fg and nxt.bg == char.bg
                            and getattr(nxt, "bold", False) == bold):
                        batch += nxt.data or " "
                    else:
                        break

                cursor.insertText(batch, self._get_fmt(fg, bg, bold))
                x += len(batch)

            if y < screen.lines - 1:
                cursor.insertText("\n", default_fmt)

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def clear_pty_region(self, start_pos: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(start_pos)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)

    def clear_screen(self) -> None:
        self.clear()

    # --- input buffer helpers ---

    def read_input(self) -> str:
        cursor = self.textCursor()
        cursor.setPosition(self._prompt_end)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace("\u2029", "\n")

    def write_input(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self._prompt_end)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)

    def commit_input(self) -> None:
        self._goto_end()
        self.insertPlainText("\n")

    def clamp_cursor_to_input(self) -> None:
        if self.textCursor().position() < self._prompt_end:
            self._goto_end()

    def _goto_end(self) -> None:
        self.moveCursor(QTextCursor.MoveOperation.End)
