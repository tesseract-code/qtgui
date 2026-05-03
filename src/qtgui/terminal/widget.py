from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pyte
from PyQt6.QtCore import QTimer, Qt, QObject, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QCompleter


from qtgui.terminal.display import TerminalDisplay, Palette
from qtgui.terminal.history import TerminalHistory
from qtgui.terminal.process.ptyprocess import PtyProcess
from qtgui.terminal.process.qtprocess import TerminalProcess
from qtgui.terminal.utils import HAS_PTY, UNIX_COMPLETIONS, _key_to_bytes, \
    TUI_PROGRAMS


class TerminalWidget(QWidget):
    """
    Wires TerminalDisplay + TerminalProcess + TerminalHistory together,
    delegating to PtyProcess for programs that require a real PTY.

    Design
    ------
    * Composition over inheritance: TerminalDisplay is held as self._display,
      not subclassed.  This enforces the rendering/logic boundary.
    * Keystrokes are captured via QObject.eventFilter() installed on the
      display.  Returning False lets the display's QTextEdit handle the key
      normally; returning True consumes it.
    * completer refresh is driven by TerminalDisplay.textChanged so it
      fires correctly for every edit regardless of how the text changed.

    Public API
    ----------
    set_cwd(path: str | Path)
        Change the working directory without running a shell command.
    """

    PTY_COLS = 80
    PTY_ROWS = 24

    # History debounce: flush to disk this many ms after the last command.
    _SAVE_DEBOUNCE_MS = 2_000

    def __init__(self) -> None:
        super().__init__()

        self._cwd = os.getcwd()

        # ── Sub-components ────────────────────────────────────────────────
        self._display = TerminalDisplay()
        self._history = TerminalHistory()
        self._proc    = TerminalProcess(cwd=self._cwd, parent=self)

        # ── PTY state ─────────────────────────────────────────────────────
        # Always initialised so attribute access is unconditionally safe;
        # None when pyte is unavailable.
        self._pty_mode: bool = False
        self._pty_proc: Optional[PtyProcess] = None
        self._pty_start_pos: int = 0
        if HAS_PTY:
            self._screen: Optional["pyte.Screen"]      = pyte.Screen(self.PTY_COLS, self.PTY_ROWS)
            self._pyte_stream: Optional["pyte.ByteStream"] = pyte.ByteStream(self._screen)
        else:
            self._screen      = None
            self._pyte_stream = None

        # ── History save debounce ─────────────────────────────────────────
        # Saves at most once per _SAVE_DEBOUNCE_MS ms; always flushed on close.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self._SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._history.save)

        # ── Layout ────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._display)

        # ── Event filter (replaces keyPressEvent override on TerminalDisplay)
        self._display.installEventFilter(self)

        self._setup_signals()
        self._setup_completer()
        self._display.render_prompt(self._cwd)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_cwd(self, path: str | Path) -> None:
        """
        Change the terminal's working directory programmatically.

        Resolves and validates *path* without executing any shell command.
        The prompt is redrawn immediately to reflect the new location.

        Raises
        ------
        NotADirectoryError  if the resolved path is not an existing directory.
        OSError             if the path cannot be resolved (e.g. permission).

        Example
        -------
        terminal.set_cwd("/tmp")
        terminal.set_cwd(Path.home() / "projects")
        """
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {resolved}")
        self._cwd = str(resolved)
        self._proc.update_cwd(self._cwd)
        self._display.render_prompt(self._cwd)

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _setup_signals(self) -> None:
        self._proc.stdout_ready.connect(self._display.append_output)
        self._proc.stderr_ready.connect(
            lambda text: self._display.append_output(text, Palette.ERROR)
        )
        self._proc.finished.connect(lambda: self._display.render_prompt(self._cwd))
        # Drive completer refresh on every text change in the display.
        self._display.textChanged.connect(self._refresh_completer)

    def _setup_completer(self) -> None:
        self._completer = QCompleter(UNIX_COMPLETIONS, self)
        self._completer.setWidget(self._display)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.activated.connect(self._display.write_input)

    # ------------------------------------------------------------------
    # Event filter — intercepts keystrokes on TerminalDisplay
    # ------------------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._display and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            return self._handle_key(event)
        return False

    def _handle_key(self, event: QKeyEvent) -> bool:
        """
        Handle a key event forwarded from TerminalDisplay.

        Returns True to consume the event (stop propagation) or False to
        let TerminalDisplay's QTextEdit process it normally.
        """
        # PTY mode: route every keystroke to the child process directly.
        if self._pty_mode and self._pty_proc:
            data = _key_to_bytes(event)
            if data:
                self._pty_proc.write(data)
            return True   # always consume in PTY mode

        self._display.clamp_cursor_to_input()

        key = event.key()

        if key == Qt.Key.Key_Escape:
            if self._completer.popup().isVisible():
                self._completer.popup().hide()
            return True

        if key == Qt.Key.Key_Return:
            self._on_return()
            return True

        if key == Qt.Key.Key_Tab:
            self._on_tab()
            return True

        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._on_history_nav(key)
            return True

        if key == Qt.Key.Key_Backspace:
            if self._display.textCursor().position() <= self._display._prompt_end:
                return True   # swallow — cannot delete past the prompt

        # All other keys: let TerminalDisplay (QTextEdit) handle them.
        # _refresh_completer is driven by textChanged, so no manual call needed.
        return False

    # --- key sub-handlers ---

    def _on_return(self) -> None:
        cmd = self._display.read_input().strip()
        self._display.commit_input()
        self._execute(cmd)

    def _on_tab(self) -> None:
        prefix = self._display.read_input()
        if not prefix:
            return
        self._completer.setCompletionPrefix(prefix)
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self._display.cursorRect()
        rect.setWidth(
            popup.sizeHintForColumn(0)
            + popup.verticalScrollBar().sizeHint().width()
        )
        self._completer.complete(rect)

    def _on_history_nav(self, key: Qt.Key) -> None:
        entry = (
            self._history.older() if key == Qt.Key.Key_Up
            else self._history.newer()
        )
        if entry is not None:
            self._display.write_input(entry)

    def _refresh_completer(self) -> None:
        prefix = self._display.read_input()
        if not prefix:
            self._completer.popup().hide()
            return
        if prefix != self._completer.completionPrefix():
            self._completer.setCompletionPrefix(prefix)

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def _execute(self, cmd: str) -> None:
        if not cmd:
            self._display.render_prompt(self._cwd)
            return

        self._history.push(cmd)
        self._save_timer.start()   # reset debounce window

        if cmd == "clear":
            self._display.clear_screen()
            self._display.render_prompt(self._cwd)
            return

        if cmd.startswith("cd"):
            self._builtin_cd(cmd)
            return

        prog = cmd.split()[0]
        if prog in TUI_PROGRAMS:
            if HAS_PTY:
                self._start_tui(cmd)
            else:
                self._display.append_output(
                    f"⚠  '{prog}' needs PTY support.\n"
                    f"   Run:  pip install pyte\n",
                    Palette.WARN,
                )
                self._display.render_prompt(self._cwd)
            return

        self._proc.run(cmd)

    def _builtin_cd(self, cmd: str) -> None:
        parts  = cmd.split(maxsplit=1)
        raw    = parts[1].strip() if len(parts) > 1 else "~"
        target = os.path.expanduser(raw)
        # Resolve relative to our privately tracked cwd — never os.getcwd()
        new_path = (Path(self._cwd) / target).resolve()
        try:
            if not new_path.exists():
                raise FileNotFoundError(f"No such file or directory: {new_path}")
            if not new_path.is_dir():
                raise NotADirectoryError(f"Not a directory: {new_path}")
            self._cwd = str(new_path)
            self._proc.update_cwd(self._cwd)
        except OSError as exc:
            self._display.append_output(f"{exc}\n", Palette.ERROR)
        self._display.render_prompt(self._cwd)

    # ------------------------------------------------------------------
    # PTY / TUI mode
    # ------------------------------------------------------------------

    def _start_tui(self, cmd: str) -> None:
        # Guard against re-entry: a second call while a TUI is active would
        # previously overwrite self._pty_proc, leaking the fd and orphaning
        # the child process.
        if self._pty_proc is not None:
            return

        self._screen.reset()
        self._pty_mode = True
        self._display._goto_end()
        self._display.insertPlainText("\n")
        self._pty_start_pos = self._display.textCursor().position()

        self._pty_proc = PtyProcess(self)
        self._pty_proc.output_ready.connect(self._on_pty_output)
        self._pty_proc.finished.connect(self._on_tui_finished)
        self._pty_proc.start(cmd, self._cwd, cols=self.PTY_COLS, rows=self.PTY_ROWS)

    def _on_pty_output(self, data: bytes) -> None:
        # Guard is safe: _pyte_stream / _screen are always None together.
        if self._pyte_stream is None or self._screen is None:
            return
        self._pyte_stream.feed(data)
        self._display.render_pty_screen(self._screen, self._pty_start_pos)

    def _on_tui_finished(self) -> None:
        self._pty_mode = False
        self._display.clear_pty_region(self._pty_start_pos)
        # deleteLater schedules Qt-safe destruction; avoids use-after-free if
        # a signal from _pty_proc is still queued at this moment.
        self._pty_proc.deleteLater()
        self._pty_proc = None
        self._display.render_prompt(self._cwd)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Call super() first so the base widget tears down cleanly before
        # we release process resources.
        super().closeEvent(event)
        self._save_timer.stop()
        self._history.save()   # unconditional flush regardless of debounce state
        if self._pty_proc:
            self._pty_proc.kill()
        self._proc.kill()
