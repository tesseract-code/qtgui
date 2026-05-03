#!/usr/bin/env python3
"""
PyQt6 Multi-Language Code Editor
=================================
A modern, palette-aware code editor supporting multiple languages, with an
integrated Symbols panel (powered by symbols_view.SymbolsWidget).

Languages
---------
  Plain Text  — no highlighting
  Python      — keywords, builtins, decorators, strings, numbers, comments,
                multi-line triple-quoted strings (state machine)
  SQL         — keywords, types, functions, strings, numbers, line/block comments
  C / C++     — keywords, types, preprocessor, strings, chars, numbers,
                line and block (/* */) comments
  JavaScript  — keywords, builtins, strings (incl. template literals),
                regex literals, numbers, line/block comments
  Markdown    — headings, bold, italic, inline code, fenced code blocks, links

Language selection
------------------
  - Explicit: toolbar combo-box, always authoritative.
  - On file open: detected from file extension only — never from content.
    Extension map is strict; unknown extensions default to "Plain Text".

Symbols panel
-------------
  Toggled via View → Show Symbols (Ctrl+Shift+O).
  Refreshes automatically on tab switch and 500 ms after the last edit.
  Double-clicking a symbol navigates the editor to that line/column.
  Requires symbols_view.py alongside this file; gracefully disabled if absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QPlainTextEdit, QTextEdit, QWidget,
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox,
    QTabWidget, QDialog, QLabel, QLineEdit, QPushButton,
    QCheckBox, QToolBar, QMenu, QFontDialog, QComboBox, QSpinBox, QStatusBar,
    QMenuBar, QSplitter,
)
from PyQt6.QtCore import (
    Qt, QRect, QSize, QRegularExpression, QFileSystemWatcher, QTimer,
)
from PyQt6.QtGui import (
    QColor, QTextCharFormat, QFont, QPainter, QSyntaxHighlighter,
    QTextCursor, QKeySequence, QAction, QPalette,
    QFontMetricsF, QTextDocument,
)

# ── Optional symbols panel ────────────────────────────────────────────────────
try:
    from qtgui.file.code.symbols import SymbolsWidget
    _SYMBOLS_AVAILABLE = True
except ImportError:
    _SYMBOLS_AVAILABLE = False

# Maps editor LangInfo.name → symbols_view language tag accepted by load_source
_LANG_TO_SYMBOLS: dict[str, str] = {
    "Python":     "python",
    "SQL":        "sql",
    "C / C++":    "cpp",
    "JavaScript": "javascript",
    "Markdown":   "markdown",
}


# ══════════════════════════════════════════════════════════════════════════════
# §1  Shared highlighter infrastructure
# ══════════════════════════════════════════════════════════════════════════════

class BaseHighlighter(QSyntaxHighlighter):
    """
    Common infrastructure for all language highlighters.

    Subclasses call self._add(pattern, fmt) in _build_rules() and optionally
    register multi-line span delimiters with self._add_multiline().

    highlightBlock() applies single-line rules first, then multi-line spans,
    so spans always win (e.g. block comments override keyword matches inside
    them).  State IDs start at 1; 0 is reserved for "normal / no span".
    """

    # ── VS-Code-inspired token palette ────────────────────────────────────────
    C_KEYWORD   = QColor("#569CD6")
    C_TYPE      = QColor("#4EC9B0")
    C_FUNCTION  = QColor("#DCDCAA")
    C_STRING    = QColor("#CE9178")
    C_NUMBER    = QColor("#B5CEA8")
    C_COMMENT   = QColor("#6A9955")
    C_PREPROC   = QColor("#C586C0")
    C_SPECIAL   = QColor("#9CDCFE")
    C_REGEX     = QColor("#D16969")
    C_HEADING   = QColor("#F44747")
    C_BOLD      = QColor("#CE9178")
    C_LINK      = QColor("#4EC9B0")

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._ml_spans: list[tuple[
            QRegularExpression, QRegularExpression, int, QTextCharFormat
        ]] = []
        self._build_rules()

    @staticmethod
    def _fmt(color: QColor, bold: bool = False,
             italic: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(color)
        if bold:
            f.setFontWeight(QFont.Weight.Bold)
        if italic:
            f.setFontItalic(True)
        return f

    def _add(self, pattern: str, fmt: QTextCharFormat,
             options: QRegularExpression.PatternOption =
             QRegularExpression.PatternOption(0)):
        rx = QRegularExpression(pattern, options)
        self._rules.append((rx, fmt))

    def _add_keywords(self, words: list[str], fmt: QTextCharFormat):
        joined = "|".join(words)
        self._add(rf"\b(?:{joined})\b", fmt)

    def _add_multiline(self, open_pat: str, close_pat: str,
                       state: int, fmt: QTextCharFormat):
        self._ml_spans.append((
            QRegularExpression(open_pat),
            QRegularExpression(close_pat),
            state,
            fmt,
        ))

    def _build_rules(self):
        pass

    def highlightBlock(self, text: str):
        for rx, fmt in self._rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        self.setCurrentBlockState(0)
        for open_rx, close_rx, state, fmt in self._ml_spans:
            self._apply_multiline(text, open_rx, close_rx, state, fmt)

    def _apply_multiline(self, text: str,
                         open_rx:  QRegularExpression,
                         close_rx: QRegularExpression,
                         state:    int,
                         fmt:      QTextCharFormat):
        if self.previousBlockState() == state:
            start, add = 0, 0
        else:
            m     = open_rx.match(text)
            start = m.capturedStart() if m.hasMatch() else -1
            add   = m.capturedLength() if m.hasMatch() else 0

        while start >= 0:
            m = close_rx.match(text, start + add)
            if m.hasMatch():
                length = m.capturedStart() + m.capturedLength() - start
                self.setCurrentBlockState(0)
            else:
                self.setCurrentBlockState(state)
                length = len(text) - start
            self.setFormat(start, length, fmt)
            nxt   = open_rx.match(text, start + length)
            start = nxt.capturedStart() if nxt.hasMatch() else -1
            add   = nxt.capturedLength() if nxt.hasMatch() else 0


# ══════════════════════════════════════════════════════════════════════════════
# §2  Language highlighters
# ══════════════════════════════════════════════════════════════════════════════

class PlainHighlighter(BaseHighlighter):
    """No-op highlighter for plain text — keeps the interface uniform."""


class PythonHighlighter(BaseHighlighter):
    _KEYWORDS = [
        "False", "None", "True", "and", "as", "assert", "async", "await",
        "break", "class", "continue", "def", "del", "elif", "else",
        "except", "finally", "for", "from", "global", "if", "import",
        "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise",
        "return", "try", "while", "with", "yield",
    ]
    _BUILTINS = [
        "abs", "all", "any", "bin", "bool", "bytes", "callable", "chr",
        "classmethod", "compile", "complex", "delattr", "dict", "dir",
        "divmod", "enumerate", "eval", "exec", "filter", "float", "format",
        "frozenset", "getattr", "globals", "hasattr", "hash", "help", "hex",
        "id", "input", "int", "isinstance", "issubclass", "iter", "len",
        "list", "locals", "map", "max", "memoryview", "min", "next",
        "object", "oct", "open", "ord", "pow", "print", "property", "range",
        "repr", "reversed", "round", "set", "setattr", "slice", "sorted",
        "staticmethod", "str", "sum", "super", "tuple", "type", "vars", "zip",
    ]

    def _build_rules(self):
        self._add(r"@[\w.]+", self._fmt(self.C_PREPROC))
        self._add_keywords(self._KEYWORDS, self._fmt(self.C_KEYWORD, bold=True))
        self._add_keywords(self._BUILTINS, self._fmt(self.C_TYPE))
        self._add(r"\bdef\s+(\w+)",   self._fmt(self.C_FUNCTION))
        self._add(r"\bclass\s+(\w+)", self._fmt(self.C_TYPE, bold=True))
        self._add(r"\b(\w+)(?=\s*\()", self._fmt(self.C_FUNCTION))
        self._add(r"\b(self|cls)\b", self._fmt(self.C_SPECIAL, italic=True))
        str_fmt = self._fmt(self.C_STRING)
        for prefix in ("f", "b", "r", "rb", "br", ""):
            self._add(rf'\b{prefix}"[^"\\]*(?:\\.[^"\\]*)*"', str_fmt)
            self._add(rf"\b{prefix}'[^'\\]*(?:\\.[^'\\]*)*'", str_fmt)
        self._add(
            r"\b(?:0[xX][0-9A-Fa-f]+[lL]?|0[bB][01]+|0[oO][0-7]+"
            r"|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[jJ]?)\b",
            self._fmt(self.C_NUMBER),
        )
        self._add(r"#[^\n]*", self._fmt(self.C_COMMENT, italic=True))
        ml = self._fmt(self.C_STRING, italic=True)
        self._add_multiline('"""', '"""', 1, ml)
        self._add_multiline("'''", "'''", 2, ml)


class SQLHighlighter(BaseHighlighter):
    _KEYWORDS = [
        "ADD", "ALL", "ALTER", "AND", "ANY", "AS", "ASC", "BACKUP",
        "BETWEEN", "BY", "CASE", "CHECK", "COLUMN", "CONSTRAINT", "CREATE",
        "CROSS", "DATABASE", "DEFAULT", "DELETE", "DESC", "DISTINCT", "DROP",
        "ELSE", "END", "EXCEPT", "EXISTS", "FOREIGN", "FROM", "FULL", "GROUP",
        "HAVING", "IN", "INDEX", "INNER", "INSERT", "INTERSECT", "INTO", "IS",
        "JOIN", "LEFT", "LIKE", "LIMIT", "NOT", "NULL", "OFFSET", "ON",
        "OR", "ORDER", "OUTER", "PRIMARY", "REFERENCES", "RIGHT", "ROLLBACK",
        "SELECT", "SET", "TABLE", "TOP", "TRUNCATE", "UNION", "UNIQUE",
        "UPDATE", "VALUES", "VIEW", "WHERE", "WITH",
        "BEGIN", "COMMIT", "TRANSACTION", "EXPLAIN", "RETURNING",
    ]
    _TYPES = [
        "BIGINT", "BINARY", "BIT", "BLOB", "BOOLEAN", "CHAR", "DATE",
        "DATETIME", "DECIMAL", "DOUBLE", "ENUM", "FLOAT", "INT", "INTEGER",
        "JSON", "LONGBLOB", "LONGTEXT", "MEDIUMINT", "MEDIUMTEXT", "NCHAR",
        "NUMERIC", "NVARCHAR", "REAL", "SMALLINT", "TEXT", "TIME",
        "TIMESTAMP", "TINYINT", "UUID", "VARBINARY", "VARCHAR", "XML",
        "SERIAL", "BYTEA",
    ]
    _FUNCTIONS = [
        "AVG", "CAST", "COALESCE", "CONCAT", "COUNT", "CURRENT_DATE",
        "CURRENT_TIME", "CURRENT_TIMESTAMP", "DATE_ADD", "DATE_DIFF",
        "DATE_FORMAT", "DATEDIFF", "DAY", "FLOOR", "FORMAT", "GETDATE",
        "GROUP_CONCAT", "HOUR", "IF", "IFNULL", "ISNULL", "LENGTH", "LOWER",
        "LTRIM", "MAX", "MIN", "MOD", "MONTH", "NOW", "NULLIF", "NVL",
        "REPLACE", "ROUND", "RTRIM", "SQRT", "STRING_AGG", "STRFTIME",
        "SUBSTRING", "SUM", "TRIM", "UPPER", "YEAR",
    ]

    def _build_rules(self):
        ci = QRegularExpression.PatternOption.CaseInsensitiveOption
        self._add_keywords(self._KEYWORDS,  self._fmt(self.C_KEYWORD, bold=True))
        self._add(r"\b(?:" + "|".join(self._TYPES) + r")\b",
                  self._fmt(self.C_TYPE), ci)
        self._add(r"\b(?:" + "|".join(self._FUNCTIONS) + r")\b",
                  self._fmt(self.C_FUNCTION), ci)
        self._add(r"`[^`]*`",    self._fmt(self.C_SPECIAL))
        self._add(r"\[[^\]]*\]", self._fmt(self.C_SPECIAL))
        self._add(r"'[^'\\]*(?:\\.[^'\\]*)*'", self._fmt(self.C_STRING))
        self._add(r"\b\d+\.?\d*\b", self._fmt(self.C_NUMBER))
        self._add(r"(?::\w+|\?|\$\d+)", self._fmt(self.C_PREPROC))
        self._add(r"--[^\n]*", self._fmt(self.C_COMMENT, italic=True))
        self._add_multiline(r"/\*", r"\*/", 1,
                            self._fmt(self.C_COMMENT, italic=True))


class CHighlighter(BaseHighlighter):
    _KEYWORDS = [
        "auto", "break", "case", "const", "continue", "default", "do",
        "else", "enum", "extern", "for", "goto", "if", "inline", "register",
        "return", "sizeof", "static", "struct", "switch", "typedef", "union",
        "volatile", "while",
        "alignas", "alignof", "and", "and_eq", "asm", "bitand", "bitor",
        "catch", "class", "compl", "concept", "consteval", "constexpr",
        "constinit", "co_await", "co_return", "co_yield", "decltype",
        "delete", "explicit", "export", "false", "friend", "mutable",
        "namespace", "new", "noexcept", "not", "not_eq", "nullptr", "operator",
        "or", "or_eq", "override", "private", "protected", "public",
        "requires", "static_assert", "static_cast", "dynamic_cast",
        "reinterpret_cast", "const_cast", "template", "this", "throw", "true",
        "try", "typeid", "typename", "using", "virtual", "xor", "xor_eq",
    ]
    _TYPES = [
        "bool", "char", "char8_t", "char16_t", "char32_t", "double",
        "float", "int", "long", "ptrdiff_t", "short", "signed", "size_t",
        "ssize_t", "string", "uint8_t", "uint16_t", "uint32_t", "uint64_t",
        "int8_t", "int16_t", "int32_t", "int64_t", "unsigned", "void",
        "wchar_t", "FILE", "nullptr_t",
    ]

    def _build_rules(self):
        self._add(r"^\s*#\s*\w+",
                  self._fmt(self.C_PREPROC, bold=True),
                  QRegularExpression.PatternOption.MultilineOption)
        self._add(r'(?<=#\s*include\s)(?:<[^>]*>|"[^"]*")',
                  self._fmt(self.C_STRING))
        self._add_keywords(self._KEYWORDS, self._fmt(self.C_KEYWORD, bold=True))
        self._add_keywords(self._TYPES,    self._fmt(self.C_TYPE))
        self._add(r"\bthis\b", self._fmt(self.C_SPECIAL, italic=True))
        self._add(r"\b(\w+)(?=\s*\()", self._fmt(self.C_FUNCTION))
        self._add(r'"[^"\\]*(?:\\.[^"\\]*)*"', self._fmt(self.C_STRING))
        self._add(r"'[^'\\]*(?:\\.[^'\\]*)*'", self._fmt(self.C_STRING))
        self._add(
            r"\b(?:0[xX][0-9A-Fa-f]+[uUlL]*"
            r"|0[bB][01]+[uUlL]*"
            r"|\d+\.?\d*(?:[eE][+-]?\d+)?[fFlLuU]*)\b",
            self._fmt(self.C_NUMBER),
        )
        self._add(r"//[^\n]*", self._fmt(self.C_COMMENT, italic=True))
        self._add_multiline(r"/\*", r"\*/", 1,
                            self._fmt(self.C_COMMENT, italic=True))


class JavaScriptHighlighter(BaseHighlighter):
    _KEYWORDS = [
        "async", "await", "break", "case", "catch", "class", "const",
        "continue", "debugger", "default", "delete", "do", "else", "export",
        "extends", "false", "finally", "for", "from", "function", "if",
        "import", "in", "instanceof", "let", "new", "null", "of", "return",
        "static", "super", "switch", "this", "throw", "true", "try",
        "typeof", "undefined", "var", "void", "while", "with", "yield",
        "abstract", "as", "declare", "enum", "implements", "interface",
        "keyof", "module", "namespace", "never", "override", "private",
        "protected", "public", "readonly", "satisfies", "type", "unknown",
    ]
    _BUILTINS = [
        "Array", "Boolean", "console", "Date", "document", "Error",
        "Float32Array", "Float64Array", "Function", "Int32Array", "JSON",
        "Map", "Math", "NaN", "Number", "Object", "Promise", "Proxy",
        "RegExp", "Set", "String", "Symbol", "TypeError", "Uint8Array",
        "WeakMap", "WeakRef", "WeakSet", "window",
    ]

    def _build_rules(self):
        self._add_keywords(self._KEYWORDS, self._fmt(self.C_KEYWORD, bold=True))
        self._add_keywords(self._BUILTINS, self._fmt(self.C_TYPE))
        self._add(r"\bfunction\s+(\w+)", self._fmt(self.C_FUNCTION))
        self._add(r"\b(\w+)(?=\s*\()", self._fmt(self.C_FUNCTION))
        self._add(r"\bthis\b", self._fmt(self.C_SPECIAL, italic=True))
        self._add(r'"[^"\\]*(?:\\.[^"\\]*)*"', self._fmt(self.C_STRING))
        self._add(r"'[^'\\]*(?:\\.[^'\\]*)*'", self._fmt(self.C_STRING))
        self._add(
            r"(?<=[=(,;\[!&|?:+\-*%^~])\s*/(?:[^/\\\n]|\\.)+/[gimsuy]*",
            self._fmt(self.C_REGEX),
        )
        self._add(
            r"\b(?:0[xX][0-9A-Fa-f]+n?|0[oO][0-7]+|0[bB][01]+n?"
            r"|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?n?)\b",
            self._fmt(self.C_NUMBER),
        )
        self._add(r"//[^\n]*", self._fmt(self.C_COMMENT, italic=True))
        self._add_multiline(r"/\*", r"\*/", 1,
                            self._fmt(self.C_COMMENT, italic=True))
        self._add_multiline("`", "`", 2, self._fmt(self.C_STRING, italic=True))


class MarkdownHighlighter(BaseHighlighter):
    def _build_rules(self):
        ml = QRegularExpression.PatternOption.MultilineOption
        self._add(r"^#{1,6}\s.*$", self._fmt(self.C_HEADING, bold=True), ml)
        self._add(r"^[=\-]{2,}\s*$", self._fmt(self.C_HEADING, bold=True), ml)
        self._add(r"\*\*[^*]+\*\*|__[^_]+__",
                  self._fmt(self.C_BOLD, bold=True))
        self._add(
            r"(?<!\*)\*(?!\*)[^*]+\*(?!\*)|(?<!_)_(?!_)[^_]+_(?!_)",
            self._fmt(self.C_STRING, italic=True),
        )
        self._add(r"`[^`]+`", self._fmt(self.C_TYPE))
        self._add(r"!?\[[^\]]*\]\([^)]*\)", self._fmt(self.C_LINK))
        self._add(r"^>\s.*$", self._fmt(self.C_COMMENT, italic=True), ml)
        self._add(r"^(?:\*{3,}|-{3,}|_{3,})\s*$",
                  self._fmt(self.C_COMMENT), ml)
        self._add(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^>]*)?>",
                  self._fmt(self.C_KEYWORD))
        self._add_multiline(r"^(?:```|~~~)", r"^(?:```|~~~)", 1,
                            self._fmt(self.C_SPECIAL))


# ══════════════════════════════════════════════════════════════════════════════
# §3  Language registry
# ══════════════════════════════════════════════════════════════════════════════

class LangInfo:
    __slots__ = ("name", "highlighter_cls", "extensions",
                 "comment_prefix", "indent_colon")

    def __init__(self, name: str,
                 highlighter_cls: type[BaseHighlighter],
                 extensions: tuple[str, ...],
                 comment_prefix: str = "",
                 indent_colon: bool = False):
        self.name            = name
        self.highlighter_cls = highlighter_cls
        self.extensions      = extensions
        self.comment_prefix  = comment_prefix
        self.indent_colon    = indent_colon


LANGUAGES: list[LangInfo] = [
    LangInfo("Plain Text",  PlainHighlighter,      (),
             comment_prefix=""),
    LangInfo("Python",      PythonHighlighter,
             ("py", "pyw", "pyi", "pyx", "pxd"),
             comment_prefix="# ", indent_colon=True),
    LangInfo("SQL",         SQLHighlighter,
             ("sql", "ddl", "dml"),
             comment_prefix="-- "),
    LangInfo("C / C++",     CHighlighter,
             ("c", "h", "cpp", "cxx", "cc", "hpp", "hxx", "hh", "inl"),
             comment_prefix="// "),
    LangInfo("JavaScript",  JavaScriptHighlighter,
             ("js", "mjs", "cjs", "jsx", "ts", "tsx", "mts", "cts"),
             comment_prefix="// "),
    LangInfo("Markdown",    MarkdownHighlighter,
             ("md", "markdown", "mdx", "rst"),
             comment_prefix=""),
]

_EXT_MAP: dict[str, LangInfo] = {
    ext: lang
    for lang in LANGUAGES
    for ext in lang.extensions
}

PLAIN_TEXT = LANGUAGES[0]


def lang_from_extension(path: str | Path) -> LangInfo:
    ext = Path(path).suffix.lstrip(".").lower()
    return _EXT_MAP.get(ext, PLAIN_TEXT)


def lang_by_name(name: str) -> LangInfo:
    for lang in LANGUAGES:
        if lang.name == name:
            return lang
    return PLAIN_TEXT


# ══════════════════════════════════════════════════════════════════════════════
# §4  Line Number Area
# ══════════════════════════════════════════════════════════════════════════════

class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.lineNumberAreaPaintEvent(event)


# ══════════════════════════════════════════════════════════════════════════════
# §5  Code Editor
# ══════════════════════════════════════════════════════════════════════════════

class CodeEditor(QPlainTextEdit):
    """
    QPlainTextEdit extended with:
      - LineNumberArea in the left margin
      - Current-line highlight via QTextEdit.ExtraSelection
      - Per-language syntax highlighting
      - Auto-indent (language-aware colon detection)
      - Tab → spaces, Shift+Tab → dedent
      - Bracket / quote auto-close
      - Language-aware comment toggling
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_area   = LineNumberArea(self)
        self._highlighter: BaseHighlighter | None = None
        self._tab_size    = 4
        self._lang        = PLAIN_TEXT
        self.filepath: str | None = None

        self._setup_font()
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._connect_signals()

    def _setup_font(self):
        font = self.font()
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self._sync_tab_stop()

    def _connect_signals(self):
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_line_area_width(0)
        self._highlight_current_line()

    def _sync_tab_stop(self):
        fm = QFontMetricsF(self.font())
        self.setTabStopDistance(fm.horizontalAdvance(" ") * self._tab_size)

    # ── Language ───────────────────────────────────────────────────────────────

    def set_language(self, lang: LangInfo):
        self._lang = lang
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
        self._highlighter = lang.highlighter_cls(self.document())

    @property
    def language(self) -> LangInfo:
        return self._lang

    # ── Line numbers ───────────────────────────────────────────────────────────

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        fm     = QFontMetricsF(self.font())
        return int(fm.horizontalAdvance("9") * digits) + 20

    def _update_line_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect: QRect, dy: int):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(),
                                   self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            QRect(cr.left(), cr.top(),
                  self.line_number_area_width(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        pal = self.palette()
        p   = QPainter(self._line_area)
        bg  = pal.color(QPalette.ColorRole.Base).darker(115)
        p.fillRect(event.rect(), bg)
        p.setPen(pal.color(QPalette.ColorRole.Mid))
        p.drawLine(self._line_area.width() - 1, event.rect().top(),
                   self._line_area.width() - 1, event.rect().bottom())

        block         = self.firstVisibleBlock()
        num           = block.blockNumber()
        top           = int(self.blockBoundingGeometry(block)
                            .translated(self.contentOffset()).top())
        bottom        = top + int(self.blockBoundingRect(block).height())
        current_block = self.textCursor().blockNumber()
        fh            = int(QFontMetricsF(self.font()).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                col = (pal.color(QPalette.ColorRole.Highlight)
                       if num == current_block
                       else pal.color(QPalette.ColorRole.PlaceholderText))
                p.setPen(col)
                p.drawText(0, top,
                           self._line_area.width() - 8, fh,
                           Qt.AlignmentFlag.AlignRight,
                           str(num + 1))
            block  = block.next()
            top    = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            num   += 1
        p.end()

    # ── Current-line highlight ─────────────────────────────────────────────────

    def _highlight_current_line(self):
        extras: list[QTextEdit.ExtraSelection] = []
        if not self.isReadOnly():
            pal = self.palette()
            sel = QTextEdit.ExtraSelection()
            col = pal.color(QPalette.ColorRole.Highlight)
            col.setAlpha(30)
            sel.format.setBackground(col)
            sel.format.setProperty(
                QTextCharFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extras.append(sel)
        self.setExtraSelections(extras)

    # ── Key handling ───────────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key  = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_Tab and not mods:
            self._on_tab(); return
        if key == Qt.Key.Key_Backtab:
            self._dedent(); return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._auto_indent(); return

        _pairs = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
        if event.text() in _pairs and not mods:
            self._auto_close(event.text(), _pairs[event.text()]); return

        super().keyPressEvent(event)

    def _on_tab(self):
        cur = self.textCursor()
        if cur.hasSelection():
            self._indent_lines(cur, +1)
        else:
            cur.insertText(" " * self._tab_size)

    def _indent_lines(self, cur: QTextCursor, direction: int):
        start = cur.selectionStart()
        end   = cur.selectionEnd()
        cur.setPosition(start)
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cur.beginEditBlock()
        while cur.position() <= end:
            if direction == +1:
                cur.insertText(" " * self._tab_size)
                end += self._tab_size
            else:
                line   = cur.block().text()
                spaces = len(line) - len(line.lstrip(" "))
                remove = min(spaces, self._tab_size)
                for _ in range(remove):
                    cur.deleteChar()
                end -= remove
            if not cur.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cur.endEditBlock()

    def _dedent(self):
        self._indent_lines(self.textCursor(), -1)

    def _auto_indent(self):
        cur  = self.textCursor()
        line = cur.block().text()
        n    = len(line) - len(line.lstrip())
        pad  = " " * n
        if self._lang.indent_colon and line.rstrip().endswith(":"):
            pad += " " * self._tab_size
        cur.insertText("\n" + pad)

    def _auto_close(self, open_ch: str, close_ch: str):
        cur = self.textCursor()
        cur.insertText(open_ch + close_ch)
        cur.movePosition(QTextCursor.MoveOperation.Left)
        self.setTextCursor(cur)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_tab_size(self, size: int):
        self._tab_size = size
        self._sync_tab_stop()

    def goto_line(self, line: int):
        """Move the cursor to the start of *line* (1-based) and centre it."""
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        cur.movePosition(
            QTextCursor.MoveOperation.Down,
            QTextCursor.MoveMode.MoveAnchor,
            max(0, line - 1),
        )
        self.setTextCursor(cur)
        self.centerCursor()

    def goto_line_col(self, line: int, col: int):
        """
        Move the cursor to *line* (1-based) and *col* (0-based), then centre.
        Called by the symbols panel's symbol_activated signal.
        """
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        cur.movePosition(
            QTextCursor.MoveOperation.Down,
            QTextCursor.MoveMode.MoveAnchor,
            max(0, line - 1),
        )
        if col > 0:
            cur.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.MoveAnchor,
                col,
            )
        self.setTextCursor(cur)
        self.centerCursor()
        self.setFocus()


# ══════════════════════════════════════════════════════════════════════════════
# §6  Find / Replace dialog
# ══════════════════════════════════════════════════════════════════════════════

class FindReplaceDialog(QDialog):
    def __init__(self, editor: CodeEditor, parent=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle("Find & Replace")
        self._editor = editor
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        fr = QHBoxLayout()
        fr.addWidget(QLabel("Find:"))
        self._find_ed = QLineEdit(placeholderText="Search…")
        fr.addWidget(self._find_ed)
        root.addLayout(fr)

        rr = QHBoxLayout()
        rr.addWidget(QLabel("Replace:"))
        self._repl_ed = QLineEdit(placeholderText="Replacement…")
        rr.addWidget(self._repl_ed)
        root.addLayout(rr)

        opts = QHBoxLayout()
        self._case_cb  = QCheckBox("Match case")
        self._word_cb  = QCheckBox("Whole word")
        self._regex_cb = QCheckBox("Regex")
        for cb in (self._case_cb, self._word_cb, self._regex_cb):
            opts.addWidget(cb)
        root.addLayout(opts)

        btns = QHBoxLayout()
        for text, slot in [("Find Next",   self._find_next),
                           ("Find Prev",   self._find_prev),
                           ("Replace",     self._replace_one),
                           ("Replace All", self._replace_all)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        root.addLayout(btns)

        self._status = QLabel("")
        root.addWidget(self._status)
        self._find_ed.returnPressed.connect(self._find_next)
        self.setMinimumWidth(440)

    def _flags(self) -> QTextDocument.FindFlag:
        f = QTextDocument.FindFlag(0)
        if self._case_cb.isChecked():
            f |= QTextDocument.FindFlag.FindCaseSensitively
        if self._word_cb.isChecked():
            f |= QTextDocument.FindFlag.FindWholeWords
        return f

    def _do_find(self, backward: bool) -> QTextCursor:
        term  = self._find_ed.text()
        flags = self._flags()
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        doc   = self._editor.document()
        cur   = self._editor.textCursor()
        found = (doc.find(QRegularExpression(term), cur, flags)
                 if self._regex_cb.isChecked()
                 else doc.find(term, cur, flags))
        if found.isNull():
            wrap = QTextCursor(doc)
            wrap.movePosition(QTextCursor.MoveOperation.End
                              if backward
                              else QTextCursor.MoveOperation.Start)
            found = (doc.find(QRegularExpression(term), wrap, flags)
                     if self._regex_cb.isChecked()
                     else doc.find(term, wrap, flags))
        return found

    def _find_next(self):
        f = self._do_find(False)
        if f.isNull():
            self._status.setText("Not found.")
        else:
            self._editor.setTextCursor(f)
            self._status.setText("")

    def _find_prev(self):
        f = self._do_find(True)
        if f.isNull():
            self._status.setText("Not found.")
        else:
            self._editor.setTextCursor(f)
            self._status.setText("")

    def _replace_one(self):
        cur = self._editor.textCursor()
        if cur.hasSelection():
            cur.insertText(self._repl_ed.text())
        self._find_next()

    def _replace_all(self):
        term = self._find_ed.text()
        if not term:
            return
        doc   = self._editor.document()
        cur   = QTextCursor(doc)
        cur.movePosition(QTextCursor.MoveOperation.Start)
        flags = self._flags()
        count = 0
        cur.beginEditBlock()
        while True:
            found = (doc.find(QRegularExpression(term), cur, flags)
                     if self._regex_cb.isChecked()
                     else doc.find(term, cur, flags))
            if found.isNull():
                break
            found.insertText(self._repl_ed.text())
            cur   = found
            count += 1
        cur.endEditBlock()
        self._status.setText(f"Replaced {count} occurrence(s).")

    def set_editor(self, editor: CodeEditor):
        self._editor = editor

    def set_search_text(self, text: str):
        self._find_ed.setText(text)


# ══════════════════════════════════════════════════════════════════════════════
# §7  Go-to-Line dialog
# ══════════════════════════════════════════════════════════════════════════════

class GotoLineDialog(QDialog):
    def __init__(self, max_line: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to Line")
        lay = QHBoxLayout(self)
        lay.addWidget(QLabel("Line:"))
        self._spin = QSpinBox()
        self._spin.setRange(1, max_line)
        self._spin.setMinimumWidth(80)
        lay.addWidget(self._spin)
        ok = QPushButton("Go")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)

    def line(self) -> int:
        return self._spin.value()


# ══════════════════════════════════════════════════════════════════════════════
# §8  Main window
# ══════════════════════════════════════════════════════════════════════════════

class CodeEditorWidget(QWidget):
    def __init__(self, parent=None, show_symbols: bool = True):
        super().__init__(parent)

        # When embedded in a host that supplies its own SymbolsWidget (e.g.
        # WorkspaceManager), pass show_symbols=False to suppress the internal
        # panel and avoid having two symbol views for the same editor.
        self._show_symbols = show_symbols and _SYMBOLS_AVAILABLE

        self._find_dialog: FindReplaceDialog | None = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        # Debounce timer — symbols are refreshed 500 ms after the last edit
        # to avoid parsing on every keystroke.
        self._sym_timer = QTimer(self)
        self._sym_timer.setSingleShot(True)
        self._sym_timer.setInterval(500)
        self._sym_timer.timeout.connect(self._refresh_symbols)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._build_menus()
        self._build_toolbar()
        self._build_ui()        # creates splitter, tabs, and symbols panel
        self._build_statusbar()

        QApplication.instance().paletteChanged.connect(self._on_palette_changed)

        self.add_new_tab()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_menus(self):
        self._menu_bar = QMenuBar()
        self._main_layout.addWidget(self._menu_bar)

        fm = self._menu_bar.addMenu("&File")
        self._act(fm, "&New",       self.add_new_tab,  "Ctrl+N")
        self._act(fm, "&Open…",     self._open_file,   "Ctrl+O")
        fm.addSeparator()
        self._act(fm, "&Save",      self._save,        "Ctrl+S")
        self._act(fm, "Save &As…",  self._save_as,     "Ctrl+Shift+S")
        self._act(fm, "Save A&ll",  self._save_all,    "Ctrl+Alt+S")
        fm.addSeparator()
        self._act(fm, "&Close Tab",
                  lambda: self._close_tab(self._tabs.currentIndex()),
                  "Ctrl+W")
        fm.addSeparator()
        self._act(fm, "&Quit", self.close, "Ctrl+Q")

        em = self._menu_bar.addMenu("&Edit")
        self._act(em, "&Undo",            self._undo,            "Ctrl+Z")
        self._act(em, "&Redo",            self._redo,            "Ctrl+Y")
        em.addSeparator()
        self._act(em, "Cu&t",             self._cut,             "Ctrl+X")
        self._act(em, "&Copy",            self._copy,            "Ctrl+C")
        self._act(em, "&Paste",           self._paste,           "Ctrl+V")
        self._act(em, "Select &All",      self._select_all,      "Ctrl+A")
        em.addSeparator()
        self._act(em, "&Find & Replace…", self._show_find,       "Ctrl+H")
        self._act(em, "Find &Next",       self._find_next_quick, "F3")
        self._act(em, "Go to &Line…",     self._goto_line,       "Ctrl+G")
        em.addSeparator()
        self._act(em, "Toggle &Comment",  self._toggle_comment,  "Ctrl+/")
        self._act(em, "&Duplicate Line",  self._duplicate_line,  "Ctrl+D")
        self._act(em, "&Sort Lines",      self._sort_lines)

        vm = self._menu_bar.addMenu("&View")
        self._act(vm, "Zoom &In",    self._zoom_in,    "Ctrl+=")
        self._act(vm, "Zoom &Out",   self._zoom_out,   "Ctrl+-")
        self._act(vm, "Reset &Zoom", self._zoom_reset, "Ctrl+0")
        vm.addSeparator()
        self._act(vm, "&Font…", self._choose_font)
        self._ww_act = QAction("&Word Wrap", self, checkable=True)
        self._ww_act.triggered.connect(self._toggle_wrap)
        vm.addAction(self._ww_act)

        if self._show_symbols:
            vm.addSeparator()
            self._sym_act = QAction("Show &Symbols", self, checkable=True)
            self._sym_act.setShortcut(QKeySequence("Ctrl+Shift+O"))
            self._sym_act.setChecked(True)
            self._sym_act.triggered.connect(self._toggle_symbols)
            vm.addAction(self._sym_act)
            self.addAction(self._sym_act)

    def _act(self, menu: QMenu, label: str, slot,
             shortcut: str | None = None) -> QAction:
        a = QAction(label, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_toolbar(self):
        self._toolbar = QToolBar("Main")
        self._toolbar.setMovable(False)
        self._main_layout.addWidget(self._toolbar)

        for label, slot, tip in [
            ("New",  self.add_new_tab, "New file (Ctrl+N)"),
            ("Open", self._open_file, "Open file (Ctrl+O)"),
            ("Save", self._save,      "Save (Ctrl+S)"),
        ]:
            a = QAction(label, self)
            a.setStatusTip(tip)
            a.triggered.connect(slot)
            self._toolbar.addAction(a)

        self._toolbar.addSeparator()
        self._toolbar.addWidget(QLabel("  Language: "))
        self._lang_combo = QComboBox()
        self._lang_combo.setMinimumWidth(130)
        for lang in LANGUAGES:
            self._lang_combo.addItem(lang.name)
        self._lang_combo.currentTextChanged.connect(self._on_lang_combo_changed)
        self._toolbar.addWidget(self._lang_combo)

        self._toolbar.addSeparator()
        self._toolbar.addWidget(QLabel("  Tab size: "))
        self._tab_spin = QSpinBox()
        self._tab_spin.setRange(1, 8)
        self._tab_spin.setValue(4)
        self._tab_spin.setFixedWidth(46)
        self._tab_spin.valueChanged.connect(self._on_tab_size_changed)
        self._toolbar.addWidget(self._tab_spin)

    def _build_ui(self):
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        if self._show_symbols:
            # Left panel: symbols; right panel: editor tabs
            self._sym_widget = SymbolsWidget()
            self._sym_widget.setMinimumWidth(180)
            self._sym_widget.symbol_activated.connect(self._on_symbol_activated)

            self._splitter = QSplitter(Qt.Orientation.Horizontal)
            self._splitter.addWidget(self._sym_widget)
            self._splitter.addWidget(self._tabs)
            # Symbols panel starts at ~220 px; editor takes the rest
            self._splitter.setSizes([220, 9999])
            self._splitter.setCollapsible(0, True)
            self._splitter.setCollapsible(1, False)
            self._main_layout.addWidget(self._splitter, stretch=1)
        else:
            self._sym_widget = None
            self._splitter   = None
            self._main_layout.addWidget(self._tabs, stretch=1)

    def _build_statusbar(self):
        self._status_bar = QStatusBar()
        self._lbl_pos   = QLabel("Ln 1, Col 1")
        self._lbl_lines = QLabel("0 lines")
        self._lbl_lang  = QLabel("Plain Text")
        self._lbl_enc   = QLabel("UTF-8")
        for w in (self._lbl_pos, self._lbl_lines,
                  self._lbl_lang, self._lbl_enc):
            self._status_bar.addPermanentWidget(w)
        self._main_layout.addWidget(self._status_bar)

    # ── Symbols panel ─────────────────────────────────────────────────────────

    def _refresh_symbols(self):
        """Re-parse the current editor's content and push it to the symbols panel."""
        if not _SYMBOLS_AVAILABLE or self._sym_widget is None:
            return
        ed = self._cur()
        if ed is None:
            self._sym_widget.clear()
            return

        lang_tag = _LANG_TO_SYMBOLS.get(ed.language.name)
        if lang_tag is None:
            # Plain Text or an unsupported language — clear the panel
            self._sym_widget.clear()
            return

        source = ed.toPlainText()
        self._sym_widget.load_source(source, lang_tag)

    def _on_symbol_activated(self, line: int, col: int):
        """Navigate the active editor to the symbol's position."""
        ed = self._cur()
        if ed:
            ed.goto_line_col(line, col)

    def _toggle_symbols(self, visible: bool):
        """Show or hide the symbols panel without destroying its state."""
        if self._sym_widget is not None:
            self._sym_widget.setVisible(visible)

    # ── Tab helpers ────────────────────────────────────────────────────────────

    def add_new_tab(self, filepath: str | None = None) -> CodeEditor:
        ed   = CodeEditor()
        lang = lang_from_extension(filepath) if filepath else PLAIN_TEXT
        ed.cursorPositionChanged.connect(self._update_status)
        ed.document().modificationChanged.connect(self._update_tab_title)
        ed.document().blockCountChanged.connect(self._update_status)
        # Kick off the debounce timer whenever the document content changes
        ed.document().contentsChanged.connect(self._sym_timer.start)

        title = Path(filepath).name if filepath else "untitled"
        idx   = self._tabs.addTab(ed, title)
        self._tabs.setCurrentIndex(idx)

        ed.set_language(lang)

        if filepath:
            self._load_into(ed, filepath)
        else:
            self._sync_lang_combo(lang)
        return ed

    def _cur(self) -> CodeEditor | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, CodeEditor) else None

    def _close_tab(self, idx: int):
        ed: CodeEditor = self._tabs.widget(idx)
        if ed.document().isModified():
            name  = self._tabs.tabText(idx).rstrip("*")
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                f"'{name}' has unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self._tabs.setCurrentIndex(idx)
                self._save()
        if ed.filepath and ed.filepath in self._watcher.files():
            self._watcher.removePath(ed.filepath)
        self._tabs.removeTab(idx)
        if self._tabs.count() == 0:
            self.add_new_tab()

    def _on_tab_changed(self, _idx: int):
        self._update_status()
        ed = self._cur()
        if ed:
            self._sync_lang_combo(ed.language)
            if self._find_dialog:
                self._find_dialog.set_editor(ed)
        # Refresh immediately on tab switch; cancel any pending debounce first
        self._sym_timer.stop()
        self._refresh_symbols()

    def _update_tab_title(self):
        ed = self._cur()
        if not ed:
            return
        idx  = self._tabs.currentIndex()
        name = Path(ed.filepath).name if ed.filepath else "untitled"
        self._tabs.setTabText(
            idx, name + ("*" if ed.document().isModified() else ""))

    # ── Language combo ─────────────────────────────────────────────────────────

    def _sync_lang_combo(self, lang: LangInfo):
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentText(lang.name)
        self._lang_combo.blockSignals(False)
        self._lbl_lang.setText(lang.name)

    def _on_lang_combo_changed(self, name: str):
        """User explicitly picked a language — apply it and refresh symbols."""
        ed = self._cur()
        if not ed:
            return
        lang = lang_by_name(name)
        ed.set_language(lang)
        self._lbl_lang.setText(lang.name)
        # Language change invalidates the current symbol parse immediately
        self._sym_timer.stop()
        self._refresh_symbols()

    # ── File I/O ───────────────────────────────────────────────────────────────

    def _load_into(self, ed: CodeEditor, path: str):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            QMessageBox.critical(self, "Open Error", str(exc))
            return
        ed.setPlainText(text)
        ed.filepath = path
        ed.document().setModified(False)
        self._watcher.addPath(path)
        idx  = self._tabs.indexOf(ed)
        lang = lang_from_extension(path)
        ed.set_language(lang)
        self._tabs.setTabText(idx, Path(path).name)
        self._tabs.setTabToolTip(idx, path)
        self._sync_lang_combo(lang)
        self._refresh_symbols()

    def _open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open", "",
            "All files (*);;"
            "Python (*.py *.pyw *.pyi *.pyx);;"
            "SQL (*.sql *.ddl *.dml);;"
            "C / C++ (*.c *.h *.cpp *.cxx *.cc *.hpp *.hxx);;"
            "JavaScript / TypeScript (*.js *.mjs *.jsx *.ts *.tsx);;"
            "Markdown (*.md *.markdown *.mdx *.rst);;"
            "Text (*.txt)",
        )
        for path in paths:
            for i in range(self._tabs.count()):
                ed: CodeEditor = self._tabs.widget(i)
                if ed.filepath == path:
                    self._tabs.setCurrentIndex(i)
                    break
            else:
                self.add_new_tab(path)

    def _save(self) -> bool:
        ed = self._cur()
        if not ed:
            return False
        return self._write(ed, ed.filepath) if ed.filepath else self._save_as()

    def _save_as(self) -> bool:
        ed = self._cur()
        if not ed:
            return False
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", ed.filepath or "",
            "All files (*);;"
            "Python (*.py);;"
            "SQL (*.sql);;"
            "C / C++ (*.cpp *.c *.h);;"
            "JavaScript (*.js *.ts);;"
            "Markdown (*.md)",
        )
        if not path:
            return False
        lang = lang_from_extension(path)
        ed.set_language(lang)
        self._sync_lang_combo(lang)
        return self._write(ed, path)

    def _save_all(self):
        saved = self._tabs.currentIndex()
        for i in range(self._tabs.count()):
            self._tabs.setCurrentIndex(i)
            self._save()
        self._tabs.setCurrentIndex(saved)

    def _write(self, ed: CodeEditor, path: str) -> bool:
        try:
            self._watcher.removePath(path)
            Path(path).write_text(ed.toPlainText(), encoding="utf-8")
            self._watcher.addPath(path)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))
            return False
        ed.filepath = path
        ed.document().setModified(False)
        self._update_tab_title()
        self._status_bar.showMessage(f"Saved {path}", 3000)
        return True

    def _on_file_changed(self, path: str):
        for i in range(self._tabs.count()):
            ed: CodeEditor = self._tabs.widget(i)
            if ed.filepath == path:
                reply = QMessageBox.question(
                    self, "File Changed",
                    f"'{Path(path).name}' was modified externally.  Reload?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._load_into(ed, path)
                self._watcher.addPath(path)
                break

    # ── Edit commands ──────────────────────────────────────────────────────────

    def _undo(self):       e = self._cur(); e and e.undo()
    def _redo(self):       e = self._cur(); e and e.redo()
    def _cut(self):        e = self._cur(); e and e.cut()
    def _copy(self):       e = self._cur(); e and e.copy()
    def _paste(self):      e = self._cur(); e and e.paste()
    def _select_all(self): e = self._cur(); e and e.selectAll()

    def _toggle_comment(self):
        ed = self._cur()
        if not ed:
            return
        prefix = ed.language.comment_prefix
        if not prefix:
            return
        cur   = ed.textCursor()
        start = cur.selectionStart()
        end   = cur.selectionEnd()
        cur.setPosition(start)
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cur.beginEditBlock()
        stripped_prefix = prefix.rstrip()
        while cur.position() <= end:
            line = cur.block().text()
            if line.lstrip().startswith(stripped_prefix):
                idx = line.find(stripped_prefix)
                cur.movePosition(QTextCursor.MoveOperation.Right,
                                 QTextCursor.MoveMode.MoveAnchor, idx)
                for _ in stripped_prefix:
                    cur.deleteChar()
                if cur.block().text()[idx:idx + 1] == " ":
                    cur.deleteChar()
                end -= len(prefix)
            else:
                cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cur.insertText(prefix)
                end += len(prefix)
            if not cur.movePosition(QTextCursor.MoveOperation.NextBlock):
                break
        cur.endEditBlock()

    def _duplicate_line(self):
        ed = self._cur()
        if not ed:
            return
        cur = ed.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                         QTextCursor.MoveMode.KeepAnchor)
        line = cur.selectedText()
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        cur.insertText("\n" + line)

    def _sort_lines(self):
        ed = self._cur()
        if not ed:
            return
        cur   = ed.textCursor()
        start = cur.selectionStart()
        end   = cur.selectionEnd()
        cur.setPosition(start)
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                         QTextCursor.MoveMode.KeepAnchor)
        lines = cur.selectedText().split("\u2029")
        lines.sort(key=str.casefold)
        cur.insertText("\u2029".join(lines))

    # ── Find & Replace ─────────────────────────────────────────────────────────

    def _show_find(self):
        ed = self._cur()
        if not ed:
            return
        if self._find_dialog is None:
            self._find_dialog = FindReplaceDialog(ed, self)
        else:
            self._find_dialog.set_editor(ed)
        sel = ed.textCursor().selectedText()
        if sel and "\u2029" not in sel:
            self._find_dialog.set_search_text(sel)
        self._find_dialog.show()
        self._find_dialog.raise_()
        self._find_dialog.activateWindow()

    def _find_next_quick(self):
        if self._find_dialog and self._find_dialog._find_ed.text():
            self._find_dialog._find_next()
        else:
            self._show_find()

    # ── Go to Line ─────────────────────────────────────────────────────────────

    def _goto_line(self):
        ed = self._cur()
        if not ed:
            return
        dlg = GotoLineDialog(ed.blockCount(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            ed.goto_line(dlg.line())

    # ── View ───────────────────────────────────────────────────────────────────

    def _zoom_in(self):   e = self._cur(); e and e.zoomIn(2)
    def _zoom_out(self):  e = self._cur(); e and e.zoomOut(2)
    def _zoom_reset(self):
        ed = self._cur()
        if ed:
            ed._setup_font()

    def _toggle_wrap(self, checked: bool):
        ed = self._cur()
        if ed:
            ed.setLineWrapMode(
                QPlainTextEdit.LineWrapMode.WidgetWidth if checked
                else QPlainTextEdit.LineWrapMode.NoWrap)

    def _choose_font(self):
        ed = self._cur()
        if not ed:
            return
        font, ok = QFontDialog.getFont(ed.font(), self, "Editor Font")
        if ok:
            ed.setFont(font)
            fm = QFontMetricsF(font)
            ed.setTabStopDistance(fm.horizontalAdvance(" ") * ed._tab_size)

    # ── Status bar ─────────────────────────────────────────────────────────────

    def _update_status(self):
        ed = self._cur()
        if not ed:
            return
        cur = ed.textCursor()
        self._lbl_pos.setText(
            f"Ln {cur.blockNumber() + 1}, Col {cur.columnNumber() + 1}")
        self._lbl_lines.setText(f"{ed.blockCount()} lines")

    # ── Tab size ───────────────────────────────────────────────────────────────

    def _on_tab_size_changed(self, value: int):
        ed = self._cur()
        if ed:
            ed.set_tab_size(value)

    # ── Palette ────────────────────────────────────────────────────────────────

    def _on_palette_changed(self, _pal: QPalette):
        for i in range(self._tabs.count()):
            ed: CodeEditor = self._tabs.widget(i)
            ed._highlight_current_line()
            if ed._highlighter:
                ed._highlighter.rehighlight()

    # ── Close guard ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._sym_timer.stop()
        for i in range(self._tabs.count()):
            ed: CodeEditor = self._tabs.widget(i)
            if ed.document().isModified():
                name  = self._tabs.tabText(i).rstrip("*")
                reply = QMessageBox.question(
                    self, "Unsaved Changes",
                    f"'{name}' has unsaved changes. Save before quitting?",
                    QMessageBox.StandardButton.Save |
                    QMessageBox.StandardButton.Discard |
                    QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if reply == QMessageBox.StandardButton.Save:
                    self._tabs.setCurrentIndex(i)
                    if not self._save():
                        event.ignore()
                        return
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# §9  Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PyQt6 Editor")
    win = CodeEditorWidget()
    win.show()
    for arg in sys.argv[1:]:
        if Path(arg).is_file():
            win.add_new_tab(arg)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()