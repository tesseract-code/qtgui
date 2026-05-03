import re
import shutil
import struct

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from pycore.platform import IS_MACOS, IS_UNIX

if IS_UNIX:
    import fcntl
    import struct
    import termios

    try:
        import pty
        import pyte
        HAS_PTY = True
    except ImportError:
        HAS_PTY = False
else:
    HAS_PTY = False


def _resolve_shell() -> str:
    """Return the first usable shell binary, falling back to /bin/sh."""
    candidates = (
        "/bin/zsh" if IS_MACOS else "/bin/bash",
        "/bin/bash",
        "/bin/sh",
    )
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return "/bin/sh"   # last-resort; always present on POSIX


SHELL = _resolve_shell()

UNIX_COMPLETIONS: list[str] = [
    "ls -la", "cd", "pwd", "mkdir", "rm -rf", "cp", "mv", "touch", "grep",
    "find", "ssh", "scp", "chmod", "chown", "df -h", "du -sh", "ps aux",
    "kill -9", "top", "htop", "curl -I", "wget", "tar -xvf", "zip", "unzip",
    "git status", "git add .", "git commit -m", "git push", "git pull",
    "brew install", "brew update", "sudo", "nano", "vim", "cat", "tail -f",
    "less", "man", "history", "clear", "exit", "python3", "pip3 install",
]

TUI_PROGRAMS = frozenset([
    "nano", "vim", "vi", "nvim", "emacs", "htop", "top", "less", "more",
    "man", "lynx", "mutt", "mc", "ncdu", "ranger", "cmus", "w3m",
])

# CSI sequences + OSC sequences (window title / hyperlinks) + misc
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;]*[A-Za-z]"                        # CSI  ESC [ … letter
    r"|\x1b[()][AB012]"
    r"|\x1b[=>]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"           # OSC  ESC ] … BEL|ST
)


# ---------------------------------------------------------------------------
# 2. COLOUR UTILITIES
# ---------------------------------------------------------------------------

_ANSI_16: dict[str, str] = {
    "black":          "#2e3436",
    "red":            "#cc0000",
    "green":          "#4e9a06",
    "yellow":         "#c4a000",
    "blue":           "#3465a4",
    "magenta":        "#75507b",
    "cyan":           "#06989a",
    "white":          "#d3d7cf",
    "bright_black":   "#555753",
    "bright_red":     "#ef2929",
    "bright_green":   "#8ae234",
    "bright_yellow":  "#fce94f",
    "bright_blue":    "#729fcf",
    "bright_magenta": "#ad7fa8",
    "bright_cyan":    "#34e2e2",
    "bright_white":   "#eeeeec",
}

_ANSI_16_LIST = list(_ANSI_16.values())


def _256_to_hex(n: int) -> str:
    if n < 16:
        return _ANSI_16_LIST[n]
    if n < 232:
        n -= 16
        b, n = n % 6, n // 6
        g, r = n % 6, n // 6
        step = [0, 95, 135, 175, 215, 255]
        return f"#{step[r]:02x}{step[g]:02x}{step[b]:02x}"
    v = 8 + (n - 232) * 10
    return f"#{v:02x}{v:02x}{v:02x}"


def _pyte_color(color, *, default: str) -> str:
    if color == "default" or color is None:
        return default
    if isinstance(color, str):
        return color if color.startswith("#") else _ANSI_16.get(color, default)
    if isinstance(color, int):
        return _256_to_hex(color)
    if isinstance(color, tuple) and len(color) == 3:
        return "#{:02x}{:02x}{:02x}".format(*color)
    return default


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# 3. TERMINAL HISTORY  (pure Python — no Qt dependency, disk-persistent)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. TERMINAL PROCESS  (regular commands via QProcess / anonymous pipes)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. PTY PROCESS  (TUI / interactive programs — Unix only)
# ---------------------------------------------------------------------------


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


# ---------------------------------------------------------------------------
# 6. TERMINAL DISPLAY  (rendering only — no business logic)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 7. KEY → BYTES MAP  (Qt key codes → terminal escape sequences)
#    Class-level constant on TerminalWidget; defined here for readability.
# ---------------------------------------------------------------------------

_KEY_MAP: dict[Qt.Key, bytes] = {
    Qt.Key.Key_Up:        b"\x1b[A",
    Qt.Key.Key_Down:      b"\x1b[B",
    Qt.Key.Key_Right:     b"\x1b[C",
    Qt.Key.Key_Left:      b"\x1b[D",
    Qt.Key.Key_Return:    b"\r",
    Qt.Key.Key_Backspace: b"\x7f",
    Qt.Key.Key_Tab:       b"\t",
    Qt.Key.Key_Escape:    b"\x1b",
    Qt.Key.Key_Delete:    b"\x1b[3~",
    Qt.Key.Key_Home:      b"\x1b[H",
    Qt.Key.Key_End:       b"\x1b[F",
    Qt.Key.Key_PageUp:    b"\x1b[5~",
    Qt.Key.Key_PageDown:  b"\x1b[6~",
    Qt.Key.Key_F1:        b"\x1bOP",
    Qt.Key.Key_F2:        b"\x1bOQ",
    Qt.Key.Key_F3:        b"\x1bOR",
    Qt.Key.Key_F4:        b"\x1bOS",
    Qt.Key.Key_F5:        b"\x1b[15~",
    Qt.Key.Key_F6:        b"\x1b[17~",
    Qt.Key.Key_F7:        b"\x1b[18~",
    Qt.Key.Key_F8:        b"\x1b[19~",
    Qt.Key.Key_F9:        b"\x1b[20~",
    Qt.Key.Key_F10:       b"\x1b[21~",
}


def _key_to_bytes(event: QKeyEvent) -> bytes:
    if event.key() in _KEY_MAP:
        return _KEY_MAP[event.key()]
    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
        text = event.text()
        if text:
            return bytes([ord(text) & 0x1F])
    text = event.text()
    return text.encode("utf-8") if text else b""

