"""
Symbols View Widget for PyQt6.

Displays the structural symbols of a C/C++, JavaScript, Python, SQL, or
Markdown file in a tree, similar to PyCharm's Structure panel.

Classes
-------
SymbolKind
    Enumeration of recognisable symbol types.
Symbol
    Data class holding one symbol's metadata.
SymbolParser
    Abstract base for language-specific parsers.
PythonParser, CppParser, JavaScriptParser, SQLParser, MarkdownParser
    Concrete parsers.
SymbolsWidget
    The embeddable QWidget.

Signals (SymbolsWidget)
-----------------------
symbol_activated(int, int)
    Emitted with (line, column) when the user double-clicks a symbol.

Usage
-----
>>> widget = SymbolsWidget()
>>> widget.load_file("path/to/file.py")
>>> widget.symbol_activated.connect(editor.goto_line_col)
"""

from __future__ import annotations

__all__ = [
    "SymbolKind",
    "Symbol",
    "SymbolsWidget",
]

import ast
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import (
    QModelIndex,
    QRect,
    QSize,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol model
# ---------------------------------------------------------------------------

class SymbolKind(Enum):
    MODULE      = auto()
    CLASS       = auto()
    STRUCT      = auto()
    ENUM        = auto()
    INTERFACE   = auto()
    NAMESPACE   = auto()
    FUNCTION    = auto()
    METHOD      = auto()
    PROPERTY    = auto()
    VARIABLE    = auto()
    CONSTANT    = auto()
    PARAMETER   = auto()
    HEADING1    = auto()
    HEADING2    = auto()
    HEADING3    = auto()
    TABLE       = auto()
    VIEW        = auto()
    PROCEDURE   = auto()
    INDEX       = auto()
    TRIGGER     = auto()
    UNKNOWN     = auto()


# Badge label and background colour for each kind
_KIND_META: dict[SymbolKind, tuple[str, str]] = {
    SymbolKind.MODULE:    ("M",  "#5C8DD6"),
    SymbolKind.CLASS:     ("C",  "#E06C75"),
    SymbolKind.STRUCT:    ("S",  "#C678DD"),
    SymbolKind.ENUM:      ("E",  "#E5C07B"),
    SymbolKind.INTERFACE: ("I",  "#56B6C2"),
    SymbolKind.NAMESPACE: ("N",  "#7882A4"),
    SymbolKind.FUNCTION:  ("f",  "#61AFEF"),
    SymbolKind.METHOD:    ("m",  "#4CAF88"),
    SymbolKind.PROPERTY:  ("p",  "#98C379"),
    SymbolKind.VARIABLE:  ("v",  "#ABB2BF"),
    SymbolKind.CONSTANT:  ("k",  "#D19A66"),
    SymbolKind.PARAMETER: ("a",  "#7882A4"),
    SymbolKind.HEADING1:  ("H1", "#E06C75"),
    SymbolKind.HEADING2:  ("H2", "#E5C07B"),
    SymbolKind.HEADING3:  ("H3", "#98C379"),
    SymbolKind.TABLE:     ("T",  "#56B6C2"),
    SymbolKind.VIEW:      ("V",  "#C678DD"),
    SymbolKind.PROCEDURE: ("P",  "#61AFEF"),
    SymbolKind.INDEX:     ("X",  "#D19A66"),
    SymbolKind.TRIGGER:   ("TR", "#E06C75"),
    SymbolKind.UNKNOWN:   ("?",  "#5C6370"),
}

_BADGE_SIZE = 20  # px, square
_BADGE_RADIUS = 4


def _make_badge_icon(kind: SymbolKind) -> QIcon:
    """Render a small rounded-rectangle badge icon for *kind*."""
    label, colour = _KIND_META.get(kind, ("?", "#5C6370"))
    pix = QPixmap(_BADGE_SIZE, _BADGE_SIZE)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, _BADGE_SIZE, _BADGE_SIZE, _BADGE_RADIUS, _BADGE_RADIUS)
    p.fillPath(path, QColor(colour))
    font = QFont("Courier New", 8 if len(label) <= 1 else 6)
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRect(0, 0, _BADGE_SIZE, _BADGE_SIZE), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    return QIcon(pix)


# Icons are rendered on first access so no QGuiApplication is required at import time.
_ICONS: dict[SymbolKind, QIcon] = {}


def _icon_for(kind: SymbolKind) -> QIcon:
    if kind not in _ICONS:
        _ICONS[kind] = _make_badge_icon(kind)
    return _ICONS[kind]


@dataclass
class Symbol:
    name: str
    kind: SymbolKind
    line: int               # 1-based
    col: int = 0            # 0-based
    detail: str = ""        # e.g. return type or signature snippet
    children: list["Symbol"] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

class SymbolParser(ABC):
    """Return a flat-or-nested list of Symbol objects for *source*."""

    @abstractmethod
    def parse(self, source: str) -> list[Symbol]:
        ...


class PythonParser(SymbolParser):
    """Use the stdlib ``ast`` module for accurate Python symbol extraction."""

    def parse(self, source: str) -> list[Symbol]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        return self._visit_body(tree.body, source.splitlines())

    def _visit_body(self, stmts: list[ast.stmt], lines: list[str]) -> list[Symbol]:
        symbols: list[Symbol] = []
        for node in stmts:
            sym = self._node_to_symbol(node, lines)
            if sym is not None:
                symbols.append(sym)
        return symbols

    def _node_to_symbol(self, node: ast.stmt, lines: list[str]) -> Optional[Symbol]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            detail = f"({', '.join(args)})"
            kind = SymbolKind.METHOD if self._is_method_context(node) else SymbolKind.FUNCTION
            sym = Symbol(node.name, kind, node.lineno, node.col_offset, detail)
            sym.children = self._visit_body(node.body, lines)
            return sym

        if isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases] if node.bases else []
            detail = f"({', '.join(bases)})" if bases else ""
            sym = Symbol(node.name, SymbolKind.CLASS, node.lineno, node.col_offset, detail)
            sym.children = self._visit_body(node.body, lines)
            return sym

        if isinstance(node, ast.Assign):
            names = []
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.append(t.id)
            if names:
                kind = SymbolKind.CONSTANT if names[0].isupper() else SymbolKind.VARIABLE
                return Symbol(", ".join(names), kind, node.lineno, 0)

        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                return Symbol(node.target.id, SymbolKind.VARIABLE, node.lineno,
                               node.target.col_offset, ast.unparse(node.annotation))
        return None

    @staticmethod
    def _is_method_context(_node) -> bool:
        # Heuristic: AST walk doesn't carry parent info cheaply; the caller's
        # _visit_body handles nesting, so methods are disambiguated visually by
        # indentation in the tree rather than kind.
        return False


class CppParser(SymbolParser):
    """Regex-based parser for C and C++."""

    _NAMESPACE  = re.compile(r"^\s*namespace\s+(\w+)")
    _CLASS      = re.compile(r"^\s*(?:class|template\s*<[^>]*>\s*class)\s+(\w+)")
    _STRUCT     = re.compile(r"^\s*struct\s+(\w+)")
    _ENUM       = re.compile(r"^\s*enum(?:\s+class)?\s+(\w+)")
    _DEFINE     = re.compile(r"^\s*#\s*define\s+(\w+)")
    _FUNC       = re.compile(
        r"^\s*(?:(?:inline|static|virtual|explicit|constexpr|friend|override)\s+)*"
        r"(?:[\w:<>*&\s]+?)\s+"        # return type
        r"(~?\w+)\s*\("               # name (
        r"([^)]*)\)"                   # params
        r"\s*(?:const)?\s*(?:\{|;)"   # body or declaration
    )

    def parse(self, source: str) -> list[Symbol]:
        symbols: list[Symbol] = []
        for lineno, raw in enumerate(source.splitlines(), 1):
            line = raw.rstrip()
            if m := self._NAMESPACE.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.NAMESPACE, lineno))
            elif m := self._CLASS.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.CLASS, lineno))
            elif m := self._STRUCT.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.STRUCT, lineno))
            elif m := self._ENUM.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.ENUM, lineno))
            elif m := self._DEFINE.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.CONSTANT, lineno))
            elif m := self._FUNC.match(line):
                name = m.group(1)
                params = m.group(2).strip()
                if name not in {"if", "for", "while", "switch", "return", "else"}:
                    symbols.append(Symbol(name, SymbolKind.FUNCTION, lineno, detail=f"({params})"))
        return symbols


class JavaScriptParser(SymbolParser):
    """Regex-based parser for JavaScript / TypeScript."""

    _CLASS        = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)")
    _FUNC_DECL    = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\(")
    _ARROW_CONST  = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(?[^)]*\)?\s*=>")
    _FUNC_CONST   = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function")
    _METHOD       = re.compile(r"^\s*(?:async\s+)?(?:static\s+)?(?:get\s+|set\s+)?(\w+)\s*\([^)]*\)\s*\{")
    _CONST        = re.compile(r"^\s*(?:export\s+)?const\s+([A-Z_][A-Z0-9_]*)\s*=")
    _VAR          = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=")

    def parse(self, source: str) -> list[Symbol]:
        symbols: list[Symbol] = []
        for lineno, raw in enumerate(source.splitlines(), 1):
            line = raw.rstrip()
            if m := self._CLASS.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.CLASS, lineno))
            elif m := self._FUNC_DECL.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.FUNCTION, lineno))
            elif m := self._ARROW_CONST.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.FUNCTION, lineno))
            elif m := self._FUNC_CONST.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.FUNCTION, lineno))
            elif m := self._CONST.match(line):
                symbols.append(Symbol(m.group(1), SymbolKind.CONSTANT, lineno))
            elif m := self._VAR.match(line):
                name = m.group(1)
                if name not in {"default", "module", "exports"}:
                    symbols.append(Symbol(name, SymbolKind.VARIABLE, lineno))
            elif m := self._METHOD.match(line):
                name = m.group(1)
                if name not in {"if", "for", "while", "switch", "catch", "else"}:
                    symbols.append(Symbol(name, SymbolKind.METHOD, lineno))
        return symbols


class SQLParser(SymbolParser):
    """Regex-based parser for SQL DDL statements."""

    _PATTERNS: list[tuple[re.Pattern, SymbolKind]] = [
        (re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:\w+\.)?(\w+)",   re.I), SymbolKind.TABLE),
        (re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:\w+\.)?(\w+)",    re.I), SymbolKind.VIEW),
        (re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+(?:\w+\.)?(\w+)",re.I), SymbolKind.PROCEDURE),
        (re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:\w+\.)?(\w+)",re.I), SymbolKind.FUNCTION),
        (re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(\w+)",                    re.I), SymbolKind.INDEX),
        (re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+(\w+)",            re.I), SymbolKind.TRIGGER),
    ]

    def parse(self, source: str) -> list[Symbol]:
        symbols: list[Symbol] = []
        for lineno, line in enumerate(source.splitlines(), 1):
            for pattern, kind in self._PATTERNS:
                if m := pattern.search(line):
                    symbols.append(Symbol(m.group(1), kind, lineno))
                    break
        return symbols


class MarkdownParser(SymbolParser):
    """Parse ATX headings from Markdown source."""

    _HEADING = re.compile(r"^(#{1,6})\s+(.*)")

    _HEADING_KINDS = {
        1: SymbolKind.HEADING1,
        2: SymbolKind.HEADING2,
        3: SymbolKind.HEADING3,
    }

    def parse(self, source: str) -> list[Symbol]:
        symbols: list[Symbol] = []
        for lineno, line in enumerate(source.splitlines(), 1):
            if m := self._HEADING.match(line):
                level = len(m.group(1))
                title = m.group(2).strip()
                kind = self._HEADING_KINDS.get(level, SymbolKind.HEADING3)
                symbols.append(Symbol(title, kind, lineno, detail=f"H{level}"))
        return symbols


# ---------------------------------------------------------------------------
# Parser registry
# ---------------------------------------------------------------------------

_EXT_TO_PARSER: dict[str, SymbolParser] = {}


def _parsers() -> dict[str, SymbolParser]:
    global _EXT_TO_PARSER
    if not _EXT_TO_PARSER:
        py  = PythonParser()
        cpp = CppParser()
        js  = JavaScriptParser()
        sql = SQLParser()
        md  = MarkdownParser()
        _EXT_TO_PARSER = {
            ".py":   py,
            ".pyw":  py,
            ".c":    cpp,
            ".h":    cpp,
            ".cc":   cpp,
            ".cpp":  cpp,
            ".cxx":  cpp,
            ".hpp":  cpp,
            ".hxx":  cpp,
            ".js":   js,
            ".mjs":  js,
            ".cjs":  js,
            ".ts":   js,
            ".tsx":  js,
            ".jsx":  js,
            ".sql":  sql,
            ".md":   md,
            ".mdx":  md,
            ".markdown": md,
        }
    return _EXT_TO_PARSER


def parser_for(path: str) -> Optional[SymbolParser]:
    ext = os.path.splitext(path)[1].lower()
    return _parsers().get(ext)


# ---------------------------------------------------------------------------
# Qt model
# ---------------------------------------------------------------------------

_LINE_ROLE = Qt.ItemDataRole.UserRole + 1
_COL_ROLE  = Qt.ItemDataRole.UserRole + 2
_KIND_ROLE = Qt.ItemDataRole.UserRole + 3


def _build_item(sym: Symbol) -> QStandardItem:
    text = sym.name
    item = QStandardItem(text)
    item.setIcon(_icon_for(sym.kind))
    item.setEditable(False)
    item.setData(sym.line, _LINE_ROLE)
    item.setData(sym.col,  _COL_ROLE)
    item.setData(sym.kind, _KIND_ROLE)
    if sym.detail:
        item.setToolTip(f"{sym.name} {sym.detail}  [line {sym.line}]")
    else:
        item.setToolTip(f"{sym.name}  [line {sym.line}]")

    # Detail column
    detail_item = QStandardItem(sym.detail)
    detail_item.setEditable(False)
    detail_item.setForeground(QBrush(QColor("#7882A4")))

    for child in sym.children:
        child_row = _build_item(child)
        item.appendRow(child_row)

    return item


def _populate_model(model: QStandardItemModel, symbols: list[Symbol]) -> None:
    model.clear()
    model.setHorizontalHeaderLabels(["Symbol", "Detail"])
    root = model.invisibleRootItem()
    for sym in symbols:
        item = _build_item(sym)
        detail_text = item.toolTip().split("  ")[0].replace(sym.name, "").strip()
        detail_item = QStandardItem(sym.detail)
        detail_item.setEditable(False)
        detail_item.setForeground(QBrush(QColor("#7882A4")))
        root.appendRow([item, detail_item])


# ---------------------------------------------------------------------------
# Recursive filter proxy
# ---------------------------------------------------------------------------

class _SymbolFilterProxy(QSortFilterProxyModel):
    """Accept an item if its text, or any descendant's text, matches."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(0)
        self.setRecursiveFilteringEnabled(True)


# ---------------------------------------------------------------------------
# Item delegate — draws the line-number hint on the right
# ---------------------------------------------------------------------------

class _SymbolDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        super().paint(painter, option, index)
        line = index.data(_LINE_ROLE)
        if line is None:
            return
        painter.save()
        pen_color = QColor("#5C6370")
        if option.state & QStyle.StateFlag.State_Selected:
            pen_color = QColor("#ABB2BF")
        painter.setPen(pen_color)
        font = painter.font()
        font.setPointSize(max(7, font.pointSize() - 1))
        painter.setFont(font)
        text = f":{line}"
        fm = QFontMetrics(painter.font())
        tw = fm.horizontalAdvance(text)
        x = option.rect.right() - tw - 6
        y = option.rect.center().y() + fm.ascent() // 2 - 1
        painter.drawText(x, y, text)
        painter.restore()


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

_STYLE = """
QWidget#SymbolsWidget {
    background: #282C34;
}

QLineEdit#FilterEdit {
    background: #21252B;
    color: #ABB2BF;
    border: 1px solid #3E4452;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    selection-background-color: #3E4452;
}
QLineEdit#FilterEdit:focus {
    border-color: #61AFEF;
}
QLineEdit#FilterEdit::placeholder {
    color: #5C6370;
}

QTreeView#SymbolTree {
    background: #282C34;
    alternate-background-color: #2C313A;
    color: #ABB2BF;
    border: none;
    font-size: 12px;
    show-decoration-selected: 1;
    outline: none;
}
QTreeView#SymbolTree::item {
    padding: 2px 0;
    border-radius: 3px;
}
QTreeView#SymbolTree::item:selected {
    background: #3E4452;
    color: #E5C07B;
}
QTreeView#SymbolTree::item:hover:!selected {
    background: #2C313A;
}
QTreeView#SymbolTree::branch {
    background: #282C34;
}
QTreeView#SymbolTree::branch:has-children:!has-siblings:closed,
QTreeView#SymbolTree::branch:closed:has-children:has-siblings {
    image: url(none);
    border-image: none;
}
QHeaderView::section {
    background: #21252B;
    color: #5C6370;
    border: none;
    border-bottom: 1px solid #3E4452;
    padding: 3px 6px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QPushButton#ToolBtn {
    background: transparent;
    color: #5C6370;
    border: none;
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 12px;
}
QPushButton#ToolBtn:hover  { background: #3E4452; color: #ABB2BF; }
QPushButton#ToolBtn:pressed{ background: #2C313A; }
QPushButton#ToolBtn:checked{ color: #61AFEF; }

QLabel#LangBadge {
    color: #5C6370;
    font-size: 10px;
    padding: 0 4px;
}
"""


class SymbolsWidget(QWidget):
    """
    IDE-style symbol browser for C/C++, JavaScript, Python, SQL, and Markdown.

    Parameters
    ----------
    parent : QWidget, optional

    Signals
    -------
    symbol_activated(int, int)
        Emitted with (line, column) on double-click.
    """

    symbol_activated = pyqtSignal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SymbolsWidget")
        self._current_file: Optional[str] = None
        self._sort_alpha: bool = False
        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setStyleSheet(_STYLE)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet("background:#21252B; border-bottom:1px solid #3E4452;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(6, 4, 6, 4)
        tb_layout.setSpacing(4)

        self._filter_edit = QLineEdit()
        self._filter_edit.setObjectName("FilterEdit")
        self._filter_edit.setPlaceholderText("Filter symbols…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        tb_layout.addWidget(self._filter_edit)

        self._sort_btn = QPushButton("A↓")
        self._sort_btn.setObjectName("ToolBtn")
        self._sort_btn.setCheckable(True)
        self._sort_btn.setToolTip("Sort alphabetically")
        self._sort_btn.setFixedWidth(32)
        self._sort_btn.toggled.connect(self._on_sort_toggled)
        tb_layout.addWidget(self._sort_btn)

        self._expand_btn = QPushButton("⊞")
        self._expand_btn.setObjectName("ToolBtn")
        self._expand_btn.setToolTip("Expand all")
        self._expand_btn.setFixedWidth(28)
        self._expand_btn.clicked.connect(self._tree.expandAll if hasattr(self, "_tree") else lambda: None)
        tb_layout.addWidget(self._expand_btn)

        self._collapse_btn = QPushButton("⊟")
        self._collapse_btn.setObjectName("ToolBtn")
        self._collapse_btn.setToolTip("Collapse all")
        self._collapse_btn.setFixedWidth(28)
        self._collapse_btn.clicked.connect(self._tree.collapseAll if hasattr(self, "_tree") else lambda: None)
        tb_layout.addWidget(self._collapse_btn)

        self._lang_label = QLabel("")
        self._lang_label.setObjectName("LangBadge")
        tb_layout.addWidget(self._lang_label)

        root_layout.addWidget(toolbar)

        # ── Tree ─────────────────────────────────────────────────────
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(["Symbol", "Detail"])

        self._proxy = _SymbolFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._tree = QTreeView()
        self._tree.setObjectName("SymbolTree")
        self._tree.setModel(self._proxy)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setAnimated(True)
        self._tree.setHeaderHidden(False)
        self._tree.setIndentation(16)
        self._tree.setIconSize(QSize(_BADGE_SIZE, _BADGE_SIZE))
        self._tree.setItemDelegateForColumn(0, _SymbolDelegate(self))
        self._tree.doubleClicked.connect(self._on_item_double_clicked)
        self._tree.header().setStretchLastSection(True)
        self._tree.header().setMinimumSectionSize(60)
        self._tree.setColumnWidth(0, 220)

        root_layout.addWidget(self._tree, 1)

        # Wire expand/collapse now that _tree exists
        self._expand_btn.clicked.disconnect()
        self._expand_btn.clicked.connect(self._tree.expandAll)
        self._collapse_btn.clicked.disconnect()
        self._collapse_btn.clicked.connect(self._tree.collapseAll)

        # ── Status bar ───────────────────────────────────────────────
        self._status = QLabel("No file loaded")
        self._status.setStyleSheet(
            "background:#21252B; color:#5C6370; border-top:1px solid #3E4452;"
            "padding:2px 8px; font-size:10px;"
        )
        self._status.setFixedHeight(20)
        root_layout.addWidget(self._status)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_file(self, path: str) -> bool:
        """Parse *path* and populate the symbol tree.

        Parameters
        ----------
        path : str
            Absolute or relative path to a supported source file.

        Returns
        -------
        bool
            True on success, False if the file cannot be read or the
            extension is not supported.
        """
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            log.error("SymbolsWidget.load_file: not found: %s", path)
            return False

        p = parser_for(path)
        if p is None:
            self._set_status(f"Unsupported file type: {os.path.basename(path)}")
            return False

        try:
            source = open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            log.error("SymbolsWidget.load_file: %s", exc)
            return False

        symbols = p.parse(source)
        self._current_file = path
        self._load_symbols(symbols, path)
        return True

    def load_source(self, source: str, language: str) -> bool:
        """Parse *source* text for a given *language* tag.

        Parameters
        ----------
        source : str
            Raw source code.
        language : str
            One of ``"python"``, ``"c"``, ``"cpp"``, ``"javascript"``,
            ``"typescript"``, ``"sql"``, ``"markdown"``.

        Returns
        -------
        bool
            True if the language is recognised, False otherwise.
        """
        _map = {
            "python": ".py", "c": ".c", "cpp": ".cpp", "c++": ".cpp",
            "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts",
            "sql": ".sql", "markdown": ".md", "md": ".md",
        }
        ext = _map.get(language.lower())
        if ext is None:
            return False
        p = _parsers().get(ext)
        if p is None:
            return False
        symbols = p.parse(source)
        self._load_symbols(symbols, language)
        return True

    def clear(self) -> None:
        """Remove all symbols and reset the widget."""
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["Symbol", "Detail"])
        self._current_file = None
        self._lang_label.setText("")
        self._set_status("No file loaded")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_symbols(self, symbols: list[Symbol], label: str) -> None:
        _populate_model(self._model, symbols)

        if self._sort_alpha:
            self._proxy.sort(0, Qt.SortOrder.AscendingOrder)
        else:
            self._proxy.sort(-1)  # restore source order

        self._tree.expandAll()
        self._tree.resizeColumnToContents(0)

        ext = os.path.splitext(label)[1].upper().lstrip(".") if "." in label else label.upper()
        self._lang_label.setText(ext)

        count = self._count_all(symbols)
        name = os.path.basename(label) if os.path.sep in label or "/" in label else label
        self._set_status(f"{name}  ·  {count} symbol{'s' if count != 1 else ''}")

    def _count_all(self, symbols: list[Symbol]) -> int:
        total = 0
        for s in symbols:
            total += 1 + self._count_all(s.children)
        return total

    def _set_status(self, msg: str) -> None:
        self._status.setText(msg)

    def _on_filter_changed(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)
        if text:
            self._tree.expandAll()

    def _on_sort_toggled(self, checked: bool) -> None:
        self._sort_alpha = checked
        if checked:
            self._proxy.sort(0, Qt.SortOrder.AscendingOrder)
        else:
            self._proxy.sort(-1)

    def _on_item_double_clicked(self, proxy_index: QModelIndex) -> None:
        src_index = self._proxy.mapToSource(proxy_index)
        item = self._model.itemFromIndex(src_index)
        if item is None:
            return
        line = item.data(_LINE_ROLE)
        col  = item.data(_COL_ROLE)
        if line is not None:
            self.symbol_activated.emit(int(line), int(col or 0))


# ---------------------------------------------------------------------------
# Stand-alone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import textwrap

    _DEMO_PYTHON = textwrap.dedent("""\
        MAX_RETRIES = 3
        base_url = "https://api.example.com"

        class APIClient:
            def __init__(self, token: str):
                self.token = token

            def get(self, endpoint: str) -> dict:
                pass

            def post(self, endpoint: str, data: dict) -> dict:
                pass

        class AuthClient(APIClient):
            def login(self, username: str, password: str) -> str:
                pass

        def retry(func, retries: int = MAX_RETRIES):
            pass

        async def fetch_all(urls: list) -> list:
            pass
    """)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    w = SymbolsWidget()
    w.setWindowTitle("Symbols View")
    w.resize(400, 600)
    w.load_source(_DEMO_PYTHON, "python")
    w.symbol_activated.connect(lambda l, c: print(f"Go to line {l}, col {c}"))
    w.show()
    sys.exit(app.exec())