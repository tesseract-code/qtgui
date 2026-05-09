"""
landing.py
----------
Workspace Manager — PyCharm-style welcome / landing screen in PyQt6.

Structure mirrors JetBrains' welcome dialog:
  ┌──────────────┬─────────────────────────────────────────────┐
  │  Sidebar     │  Content panel (swaps per nav item)         │
  │  • Logo      │  Projects  /  Customize  /  Plugins  /  …  │
  │  • Nav items │                                             │
  │  • Footer    │                                             │
  └──────────────┴─────────────────────────────────────────────┘

Run standalone:
    python landing.py
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QSize, QPropertyAnimation, QEasingCurve,
    QRect, QPoint, pyqtSignal, QTimer, QParallelAnimationGroup,
    QEvent, QRectF,
)
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath,
    QPen, QBrush, QLinearGradient, QRadialGradient, QPixmap,
    QCursor, QPalette, QEnterEvent,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLineEdit, QPushButton, QStackedWidget, QSizePolicy,
    QSpacerItem, QGraphicsOpacityEffect, QLayout,
)

# ── Palette ────────────────────────────────────────────────────────────────────
C = {
    "bg_sidebar":   "#0e1016",   # deep navy — sidebar
    "bg_content":   "#13151d",   # dark content area
    "bg_card":      "#191c27",   # project card background
    "bg_card_hov":  "#1e2230",   # card hover
    "bg_input":     "#191c27",   # search input
    "bg_btn":       "#1a2438",   # secondary button bg
    "bg_btn_hov":   "#1f2d47",
    "border":       "#1e2235",   # subtle dividers
    "border_hi":    "#2a3050",   # highlighted border
    "accent":       "#00d2aa",   # teal primary
    "accent2":      "#0090ff",   # electric blue
    "accent_dim":   "#00806a",   # muted teal
    "tag_py":       "#1a3a2a",
    "tag_py_fg":    "#00d2aa",
    "tag_js":       "#1a2e1a",
    "tag_js_fg":    "#7ec850",
    "tag_rs":       "#2e1a1a",
    "tag_rs_fg":    "#e05a4e",
    "tag_cpp":      "#1a1e2e",
    "tag_cpp_fg":   "#6b9ee8",
    "text_hi":      "#d8dff0",   # primary text
    "text_mid":     "#7a8aaa",   # secondary text
    "text_dim":     "#404860",   # very dim text
    "text_accent":  "#00d2aa",
    "nav_active":   "#00d2aa",
    "nav_active_bg":"#0d1e1b",
    "nav_hover_bg": "#13192a",
    "pin":          "#ffb74d",
    "new_btn":      "#00d2aa",
    "new_btn_txt":  "#021a16",
}

# ── Fake recent-projects data ──────────────────────────────────────────────────
now = datetime.now()

PROJECTS = [
    {
        "name": "workspace-manager",
        "path": "~/dev/workspace-manager",
        "lang": "PY",
        "modified": now - timedelta(minutes=12),
        "pinned": True,
        "vcs": "git",
    },
    {
        "name": "image-pipeline",
        "path": "~/projects/image-pipeline",
        "lang": "PY",
        "modified": now - timedelta(hours=3),
        "pinned": True,
        "vcs": "git",
    },
    {
        "name": "gl-renderer",
        "path": "~/dev/gl-renderer",
        "lang": "CPP",
        "modified": now - timedelta(hours=11),
        "pinned": False,
        "vcs": "git",
    },
    {
        "name": "dashboard-ui",
        "path": "~/work/dashboard-ui",
        "lang": "JS",
        "modified": now - timedelta(days=1),
        "pinned": False,
        "vcs": "git",
    },
    {
        "name": "qtgui-toolkit",
        "path": "~/dev/qtgui-toolkit",
        "lang": "PY",
        "modified": now - timedelta(days=2),
        "pinned": False,
        "vcs": "git",
    },
    {
        "name": "async-server",
        "path": "~/work/async-server",
        "lang": "PY",
        "modified": now - timedelta(days=4),
        "pinned": False,
        "vcs": None,
    },
    {
        "name": "voxel-engine",
        "path": "~/personal/voxel-engine",
        "lang": "RS",
        "modified": now - timedelta(days=8),
        "pinned": False,
        "vcs": "git",
    },
    {
        "name": "ml-experiments",
        "path": "~/research/ml-experiments",
        "lang": "PY",
        "modified": now - timedelta(days=14),
        "pinned": False,
        "vcs": "git",
    },
]

PLUGINS = [
    {"name": "Vim Keybindings",   "desc": "Full modal editing support",              "installed": True,  "icon": "⌨"},
    {"name": "Git Integration",   "desc": "Inline blame, diff gutter, log viewer",   "installed": True,  "icon": "⑂"},
    {"name": "Material Theme",    "desc": "50+ carefully crafted colour schemes",     "installed": False, "icon": "◉"},
    {"name": "Code With Me",      "desc": "Real-time collaborative editing",          "installed": False, "icon": "⊕"},
    {"name": "Database Tools",    "desc": "SQL editor, schema browser, query runner", "installed": False, "icon": "⊞"},
    {"name": "Docker",            "desc": "Container management & run configs",       "installed": True,  "icon": "◱"},
]

THEMES = [
    {"name": "Workspace Dark",    "accent": "#00d2aa", "active": True},
    {"name": "Midnight Blue",     "accent": "#0090ff", "active": False},
    {"name": "Ember",             "accent": "#e05a4e", "active": False},
    {"name": "Arctic Light",      "accent": "#00a8d0", "active": False},
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _rel_time(dt: datetime) -> str:
    delta = now - dt
    s = int(delta.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        m = s // 60
        return f"{m} min ago"
    if s < 86400:
        h = s // 3600
        return f"{h}h ago"
    d = s // 86400
    return f"{d}d ago"


def _hex(c: str) -> QColor:
    return QColor(c)


def _font(size: int, bold: bool = False, family: str = "FreeSans") -> QFont:
    f = QFont(family, size)
    f.setBold(bold)
    return f


def _mono(size: int, bold: bool = False) -> QFont:
    return _font(size, bold, family="Liberation Mono")

# ── Reusable styled widgets ────────────────────────────────────────────────────

class _Divider(QFrame):
    def __init__(self, parent=None, vertical=False):
        super().__init__(parent)
        if vertical:
            self.setFrameShape(QFrame.Shape.VLine)
            self.setFixedWidth(1)
        else:
            self.setFrameShape(QFrame.Shape.HLine)
            self.setFixedHeight(1)
        self.setStyleSheet(f"color: {C['border']};")


class _Tag(QLabel):
    """Small language badge."""
    _COLORS = {
        "PY":  (C["tag_py"],    C["tag_py_fg"]),
        "JS":  (C["tag_js"],    C["tag_js_fg"]),
        "RS":  (C["tag_rs"],    C["tag_rs_fg"]),
        "CPP": (C["tag_cpp"],   C["tag_cpp_fg"]),
    }

    def __init__(self, lang: str, parent=None):
        super().__init__(lang, parent)
        bg, fg = self._COLORS.get(lang, (C["bg_card"], C["text_mid"]))
        self.setFont(_mono(9, bold=True))
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:3px;"
            f"padding: 1px 5px;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(30, 16)


class _PrimaryButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(_font(12, bold=True))
        self.setFixedHeight(36)
        self._apply_style(False)
        self.installEventFilter(self)

    def _apply_style(self, hovered: bool):
        bg  = "#00e8bc" if hovered else C["new_btn"]
        self.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg}; color: {C['new_btn_txt']};"
            f"  border: none; border-radius: 6px;"
            f"  padding: 0 22px;"
            f"}}"
        )

    def eventFilter(self, obj, ev):
        if obj is self:
            if ev.type() == QEvent.Type.Enter:
                self._apply_style(True)
            elif ev.type() == QEvent.Type.Leave:
                self._apply_style(False)
        return super().eventFilter(obj, ev)


class _SecondaryButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(_font(12))
        self.setFixedHeight(36)
        self._apply_style(False)
        self.installEventFilter(self)

    def _apply_style(self, hovered: bool):
        bg  = C["bg_btn_hov"] if hovered else C["bg_btn"]
        brd = C["border_hi"]  if hovered else C["border"]
        self.setStyleSheet(
            f"QPushButton {{"
            f"  background: {bg}; color: {C['text_hi']};"
            f"  border: 1px solid {brd}; border-radius: 6px;"
            f"  padding: 0 18px;"
            f"}}"
        )

    def eventFilter(self, obj, ev):
        if obj is self:
            if ev.type() == QEvent.Type.Enter:
                self._apply_style(True)
            elif ev.type() == QEvent.Type.Leave:
                self._apply_style(False)
        return super().eventFilter(obj, ev)


class _SearchBar(QLineEdit):
    def __init__(self, placeholder: str = "Search…", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFont(_font(12))
        self.setFixedHeight(34)
        self.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {C['bg_input']}; color: {C['text_hi']};"
            f"  border: 1px solid {C['border']};"
            f"  border-radius: 6px; padding: 0 12px 0 32px;"
            f"}}"
            f"QLineEdit:focus {{"
            f"  border-color: {C['accent']};"
            f"}}"
        )


# ── Logo widget ────────────────────────────────────────────────────────────────

class LogoWidget(QWidget):
    """Draws the 'WM' glyph + product name."""

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self._compact = compact
        if compact:
            self.setFixedSize(44, 44)
        else:
            self.setFixedHeight(64)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Glassy hex badge ────────────────────────────────────────────
        badge_size = 40 if self._compact else 44
        bx = 10 if self._compact else 14
        by = (self.height() - badge_size) // 2

        # Gradient fill
        grad = QLinearGradient(bx, by, bx + badge_size, by + badge_size)
        grad.setColorAt(0.0, QColor("#0d2e28"))
        grad.setColorAt(1.0, QColor("#091820"))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(C["accent"]), 1.5))
        p.drawRoundedRect(bx, by, badge_size, badge_size, 10, 10)

        # 'WM' monogram
        f = _mono(badge_size // 3, bold=True)
        p.setFont(f)
        p.setPen(QColor(C["accent"]))
        p.drawText(QRect(bx, by, badge_size, badge_size),
                   Qt.AlignmentFlag.AlignCenter, "WM")

        if not self._compact:
            # Product name
            p.setPen(QColor(C["text_hi"]))
            p.setFont(_font(13, bold=True))
            p.drawText(bx + badge_size + 10, by + 16, "Workspace")
            p.setPen(QColor(C["accent"]))
            p.setFont(_font(13, bold=True))
            p.drawText(bx + badge_size + 10, by + 33, "Manager")

        p.end()


# ── Sidebar nav item ───────────────────────────────────────────────────────────

class NavItem(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, key: str, label: str, icon: str, parent=None):
        super().__init__(parent)
        self._key    = key
        self._label  = label
        self._icon   = icon
        self._active = False
        self._hovered = False
        self.setFixedHeight(40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.installEventFilter(self)

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def eventFilter(self, obj, ev):
        if obj is self:
            if ev.type() == QEvent.Type.Enter:
                self._hovered = True; self.update()
            elif ev.type() == QEvent.Type.Leave:
                self._hovered = False; self.update()
            elif ev.type() == QEvent.Type.MouseButtonPress:
                self.clicked.emit(self._key)
        return super().eventFilter(obj, ev)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        if self._active:
            p.fillRect(0, 0, w, h, QColor(C["nav_active_bg"]))
            # Active accent bar on left
            p.fillRect(0, 6, 3, h - 12, QColor(C["nav_active"]))
        elif self._hovered:
            p.fillRect(0, 0, w, h, QColor(C["nav_hover_bg"]))

        # Icon
        p.setFont(_font(15))
        p.setPen(QColor(C["nav_active"] if self._active else C["text_mid"]))
        p.drawText(QRect(14, 0, 24, h), Qt.AlignmentFlag.AlignCenter, self._icon)

        # Label
        p.setFont(_font(12, bold=self._active))
        p.setPen(QColor(C["text_hi"] if self._active else C["text_mid"]))
        p.drawText(QRect(44, 0, w - 44, h), Qt.AlignmentFlag.AlignVCenter, self._label)
        p.end()


# ── Project card ───────────────────────────────────────────────────────────────

class ProjectCard(QWidget):
    opened = pyqtSignal(dict)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self._data    = data
        self._hovered = False
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.installEventFilter(self)
        self._build()

    def _build(self):
        ly = QHBoxLayout(self)
        ly.setContentsMargins(14, 0, 14, 0)
        ly.setSpacing(12)

        # ── Language tag ─────────────────────
        self._tag = _Tag(self._data["lang"])
        ly.addWidget(self._tag)

        # ── Text block ───────────────────────
        text_col = QWidget()
        text_ly  = QVBoxLayout(text_col)
        text_ly.setContentsMargins(0, 0, 0, 0)
        text_ly.setSpacing(2)

        name = QLabel(self._data["name"])
        name.setFont(_font(13, bold=True))
        name.setStyleSheet(f"color: {C['text_hi']};")

        path = QLabel(self._data["path"])
        path.setFont(_mono(10))
        path.setStyleSheet(f"color: {C['text_dim']};")

        text_ly.addWidget(name)
        text_ly.addWidget(path)
        ly.addWidget(text_col, stretch=1)

        # ── Right meta ───────────────────────
        right = QWidget()
        right_ly = QVBoxLayout(right)
        right_ly.setContentsMargins(0, 0, 0, 0)
        right_ly.setSpacing(4)
        right_ly.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        time_lbl = QLabel(_rel_time(self._data["modified"]))
        time_lbl.setFont(_mono(10))
        time_lbl.setStyleSheet(f"color: {C['text_dim']};")
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_ly.addWidget(time_lbl)

        badges = QWidget()
        badges_ly = QHBoxLayout(badges)
        badges_ly.setContentsMargins(0, 0, 0, 0)
        badges_ly.setSpacing(4)
        if self._data.get("vcs") == "git":
            git_lbl = QLabel("git")
            git_lbl.setFont(_mono(9))
            git_lbl.setStyleSheet(
                f"color:{C['accent_dim']}; background:#0a1f1b;"
                f"border-radius:3px; padding:1px 5px;"
            )
            badges_ly.addWidget(git_lbl)
        if self._data.get("pinned"):
            pin_lbl = QLabel("★")
            pin_lbl.setFont(_mono(9))
            pin_lbl.setStyleSheet(f"color:{C['pin']};")
            badges_ly.addWidget(pin_lbl)
        right_ly.addWidget(badges, alignment=Qt.AlignmentFlag.AlignRight)

        ly.addWidget(right)

    def _set_hovered(self, v: bool):
        self._hovered = v
        bg = C["bg_card_hov"] if v else C["bg_card"]
        brd = C["border_hi"] if v else C["border"]
        self.setStyleSheet(
            f"ProjectCard {{ background:{bg}; border:1px solid {brd};"
            f"border-radius:8px; }}"
        )

    def eventFilter(self, obj, ev):
        if obj is self:
            if ev.type() == QEvent.Type.Enter:
                self._set_hovered(True)
            elif ev.type() == QEvent.Type.Leave:
                self._set_hovered(False)
            elif ev.type() == QEvent.Type.MouseButtonDblClick:
                self.opened.emit(self._data)
        return super().eventFilter(obj, ev)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._set_hovered(False)


# ── Content panels ─────────────────────────────────────────────────────────────

class ProjectsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_cards: list[ProjectCard] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(0)

        # ── Top action bar ───────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(10)

        self._search = _SearchBar("Search projects…")
        self._search.textChanged.connect(self._filter)

        new_btn  = _PrimaryButton("＋  New Project")
        open_btn = _SecondaryButton("⊡  Open…")
        get_btn  = _SecondaryButton("↓  Get from VCS")

        top.addWidget(self._search, stretch=1)
        top.addWidget(new_btn)
        top.addWidget(open_btn)
        top.addWidget(get_btn)
        root.addLayout(top)
        root.addSpacing(20)

        # ── Section header: pinned ───────────────────────────────────
        pinned_hdr = QLabel("★  Pinned")
        pinned_hdr.setFont(_font(10, bold=True))
        pinned_hdr.setStyleSheet(
            f"color:{C['pin']}; letter-spacing:1px; padding-bottom:6px;"
        )
        root.addWidget(pinned_hdr)
        root.addSpacing(4)

        scroll_container = QWidget()
        scroll_ly = QVBoxLayout(scroll_container)
        scroll_ly.setContentsMargins(0, 0, 0, 0)
        scroll_ly.setSpacing(6)

        pinned   = [p for p in PROJECTS if p["pinned"]]
        unpinned = [p for p in PROJECTS if not p["pinned"]]

        for proj in pinned:
            card = ProjectCard(proj)
            scroll_ly.addWidget(card)
            self._all_cards.append(card)

        scroll_ly.addSpacing(14)

        recent_hdr = QLabel("RECENT")
        recent_hdr.setFont(_font(10, bold=True))
        recent_hdr.setStyleSheet(
            f"color:{C['text_dim']}; letter-spacing:2px; padding-bottom:6px;"
        )
        scroll_ly.addWidget(recent_hdr)
        scroll_ly.addSpacing(4)

        for proj in unpinned:
            card = ProjectCard(proj)
            scroll_ly.addWidget(card)
            self._all_cards.append(card)

        scroll_ly.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(scroll_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border:none; }}"
            f"QScrollBar:vertical {{"
            f"  background: {C['bg_content']}; width:6px; border:none;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {C['border_hi']}; border-radius:3px; min-height:30px;"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            f"  height:0;"
            f"}}"
        )
        root.addWidget(scroll, stretch=1)

    def _filter(self, text: str):
        for card in self._all_cards:
            name = card._data["name"].lower()
            path = card._data["path"].lower()
            visible = (not text) or (text.lower() in name) or (text.lower() in path)
            card.setVisible(visible)


class CustomizePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 32)
        root.setSpacing(0)

        hdr = QLabel("Customize your workspace")
        hdr.setFont(_font(18, bold=True))
        hdr.setStyleSheet(f"color:{C['text_hi']};")
        root.addWidget(hdr)

        sub = QLabel("Choose a colour theme, keymap, and startup behaviour.")
        sub.setFont(_font(12))
        sub.setStyleSheet(f"color:{C['text_mid']}; margin-top:6px;")
        root.addWidget(sub)
        root.addSpacing(28)

        # ── Theme tiles ──────────────────────────────────────────────
        theme_hdr = QLabel("COLOUR THEME")
        theme_hdr.setFont(_mono(10, bold=True))
        theme_hdr.setStyleSheet(
            f"color:{C['text_dim']}; letter-spacing:2px; margin-bottom:10px;"
        )
        root.addWidget(theme_hdr)

        themes_row = QHBoxLayout()
        themes_row.setSpacing(12)
        for t in THEMES:
            tile = self._make_theme_tile(t)
            themes_row.addWidget(tile)
        themes_row.addStretch()
        root.addLayout(themes_row)
        root.addSpacing(30)

        # ── Keymap ───────────────────────────────────────────────────
        km_hdr = QLabel("KEYMAP")
        km_hdr.setFont(_mono(10, bold=True))
        km_hdr.setStyleSheet(
            f"color:{C['text_dim']}; letter-spacing:2px; margin-bottom:10px;"
        )
        root.addWidget(km_hdr)

        keymaps = ["Default", "Vim", "Emacs", "VS Code", "Sublime Text"]
        km_row  = QHBoxLayout()
        km_row.setSpacing(8)
        for km in keymaps:
            is_active = (km == "Default")
            btn = _PrimaryButton(km) if is_active else _SecondaryButton(km)
            btn.setFixedWidth(110)
            km_row.addWidget(btn)
        km_row.addStretch()
        root.addLayout(km_row)
        root.addSpacing(30)

        # ── Font size slider (fake) ───────────────────────────────────
        fs_hdr = QLabel("EDITOR FONT SIZE")
        fs_hdr.setFont(_mono(10, bold=True))
        fs_hdr.setStyleSheet(
            f"color:{C['text_dim']}; letter-spacing:2px; margin-bottom:10px;"
        )
        root.addWidget(fs_hdr)

        fs_row = QHBoxLayout()
        for size, label in [("12", "Small"), ("14", "Medium ✓"), ("16", "Large"), ("18", "XL")]:
            chip = QLabel(f"  {size} px  ")
            chip.setFont(_mono(11))
            active = "14" in size
            chip.setStyleSheet(
                f"color:{C['accent'] if active else C['text_mid']};"
                f"background:{'#0d1e1b' if active else C['bg_card']};"
                f"border:1px solid {C['accent'] if active else C['border']};"
                f"border-radius:5px; padding:4px 8px;"
            )
            fs_row.addWidget(chip)
        fs_row.addStretch()
        root.addLayout(fs_row)
        root.addStretch()

    def _make_theme_tile(self, t: dict) -> QWidget:
        tile = QWidget()
        tile.setFixedSize(100, 72)
        tile.setStyleSheet(
            f"background:{C['bg_card']};"
            f"border:2px solid {t['accent'] if t['active'] else C['border']};"
            f"border-radius:8px;"
        )
        ly = QVBoxLayout(tile)
        ly.setContentsMargins(8, 6, 8, 6)
        ly.setSpacing(4)
        # Mini colour strip
        strip = QWidget()
        strip.setFixedHeight(10)
        strip.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {t['accent']}, stop:1 {C['bg_sidebar']});"
            f"border-radius:3px;"
        )
        ly.addWidget(strip)
        name = QLabel(t["name"])
        name.setFont(_font(10, bold=t["active"]))
        name.setStyleSheet(
            f"color:{t['accent'] if t['active'] else C['text_mid']}; border:none;"
        )
        ly.addWidget(name)
        if t["active"]:
            check = QLabel("✓ Active")
            check.setFont(_mono(9))
            check.setStyleSheet(f"color:{t['accent']}; border:none;")
            ly.addWidget(check)
        return tile


class PluginsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 32)
        root.setSpacing(0)

        hdr = QLabel("Plugins")
        hdr.setFont(_font(18, bold=True))
        hdr.setStyleSheet(f"color:{C['text_hi']};")
        root.addWidget(hdr)

        sub = QLabel("Extend Workspace Manager with community and first-party plugins.")
        sub.setFont(_font(12))
        sub.setStyleSheet(f"color:{C['text_mid']}; margin-top:6px;")
        root.addWidget(sub)
        root.addSpacing(20)

        search = _SearchBar("Search plugins…")
        search.setMaximumWidth(360)
        root.addWidget(search)
        root.addSpacing(18)

        # Plugin cards
        scroll_w = QWidget()
        scroll_ly = QVBoxLayout(scroll_w)
        scroll_ly.setContentsMargins(0, 0, 0, 0)
        scroll_ly.setSpacing(8)

        for pl in PLUGINS:
            card = self._plugin_card(pl)
            scroll_ly.addWidget(card)
        scroll_ly.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(scroll_w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:transparent; border:none; }}"
            f"QScrollBar:vertical {{ background:{C['bg_content']}; width:6px; }}"
            f"QScrollBar::handle:vertical {{ background:{C['border_hi']};"
            f" border-radius:3px; min-height:30px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}"
        )
        root.addWidget(scroll, stretch=1)

    def _plugin_card(self, pl: dict) -> QWidget:
        card = QWidget()
        card.setFixedHeight(70)
        card.setStyleSheet(
            f"background:{C['bg_card']}; border:1px solid {C['border']};"
            f"border-radius:8px;"
        )
        ly = QHBoxLayout(card)
        ly.setContentsMargins(16, 0, 16, 0)
        ly.setSpacing(14)

        icon_lbl = QLabel(pl["icon"])
        icon_lbl.setFont(_font(20))
        icon_lbl.setStyleSheet(f"color:{C['accent']}; border:none;")
        icon_lbl.setFixedWidth(32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ly.addWidget(icon_lbl)

        text = QWidget()
        text.setStyleSheet("background:transparent; border:none;")
        text_ly = QVBoxLayout(text)
        text_ly.setContentsMargins(0, 0, 0, 0)
        text_ly.setSpacing(3)
        n = QLabel(pl["name"])
        n.setFont(_font(13, bold=True))
        n.setStyleSheet(f"color:{C['text_hi']}; border:none;")
        d = QLabel(pl["desc"])
        d.setFont(_font(11))
        d.setStyleSheet(f"color:{C['text_mid']}; border:none;")
        text_ly.addWidget(n)
        text_ly.addWidget(d)
        ly.addWidget(text, stretch=1)

        if pl["installed"]:
            badge = QLabel("Installed")
            badge.setFont(_mono(10))
            badge.setStyleSheet(
                f"color:{C['accent']}; background:#0a1f1b;"
                f"border:1px solid {C['accent_dim']}; border-radius:4px;"
                f"padding:2px 8px;"
            )
            ly.addWidget(badge)
        else:
            install_btn = _SecondaryButton("Install")
            install_btn.setFixedWidth(88)
            install_btn.setFixedHeight(30)
            ly.addWidget(install_btn)

        return card


class LearnPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 32)
        root.setSpacing(0)

        hdr = QLabel("Learn Workspace Manager")
        hdr.setFont(_font(18, bold=True))
        hdr.setStyleSheet(f"color:{C['text_hi']};")
        root.addWidget(hdr)
        root.addSpacing(4)
        sub = QLabel("Documentation, tutorials, and release notes.")
        sub.setFont(_font(12))
        sub.setStyleSheet(f"color:{C['text_mid']};")
        root.addWidget(sub)
        root.addSpacing(28)

        resources = [
            ("📖", "Getting Started Guide",      "Build your first workspace in 5 minutes.",      C["accent"]),
            ("⚡", "Keyboard Shortcuts",          "Master the layout with essential key bindings.", C["accent2"]),
            ("🔌", "Plugin API Reference",         "Extend the workspace with your own panels.",     C["pin"]),
            ("🎬", "Video Walkthrough",            "A 12-minute tour of all major features.",        C["accent"]),
            ("📋", "Changelog — v1.0.0",           "What's new in this release.",                   C["text_mid"]),
        ]

        for icon, title, desc, color in resources:
            row = QWidget()
            row.setFixedHeight(64)
            row.setStyleSheet(
                f"background:{C['bg_card']}; border:1px solid {C['border']};"
                f"border-radius:8px; margin-bottom:0px;"
            )
            row_ly = QHBoxLayout(row)
            row_ly.setContentsMargins(18, 0, 18, 0)
            row_ly.setSpacing(16)

            ic = QLabel(icon)
            ic.setFont(_font(18))
            ic.setStyleSheet("border:none;")
            ic.setFixedWidth(28)
            row_ly.addWidget(ic)

            txt = QWidget()
            txt.setStyleSheet("background:transparent; border:none;")
            txt_ly = QVBoxLayout(txt)
            txt_ly.setContentsMargins(0, 0, 0, 0)
            txt_ly.setSpacing(3)
            t = QLabel(title)
            t.setFont(_font(13, bold=True))
            t.setStyleSheet(f"color:{color}; border:none;")
            dsc = QLabel(desc)
            dsc.setFont(_font(11))
            dsc.setStyleSheet(f"color:{C['text_mid']}; border:none;")
            txt_ly.addWidget(t)
            txt_ly.addWidget(dsc)
            row_ly.addWidget(txt, stretch=1)

            arrow = QLabel("→")
            arrow.setFont(_font(16))
            arrow.setStyleSheet(f"color:{C['text_dim']}; border:none;")
            row_ly.addWidget(arrow)
            root.addWidget(row)
            root.addSpacing(8)

        root.addStretch()


# ── Sidebar ────────────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    nav_changed = pyqtSignal(str)

    NAV = [
        ("projects",   "Projects",   "◫"),
        ("customize",  "Customize",  "◈"),
        ("plugins",    "Plugins",    "⊕"),
        ("learn",      "Learn",      "◎"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet(f"background:{C['bg_sidebar']};")
        self._items: dict[str, NavItem] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Logo ─────────────────────────────────────────────────────
        logo = LogoWidget()
        logo.setFixedHeight(76)
        root.addWidget(logo)

        root.addWidget(_Divider())
        root.addSpacing(8)

        # ── Nav items ─────────────────────────────────────────────────
        for key, label, icon in self.NAV:
            item = NavItem(key, label, icon)
            item.clicked.connect(self._on_nav_clicked)
            root.addWidget(item)
            self._items[key] = item

        root.addStretch()
        root.addWidget(_Divider())

        # ── Footer ───────────────────────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(56)
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(14, 8, 14, 8)
        fl.setSpacing(2)

        ver_lbl = QLabel("v1.0.0")
        ver_lbl.setFont(_mono(10))
        ver_lbl.setStyleSheet(f"color:{C['text_dim']};")

        update_lbl = QLabel("Check for updates…")
        update_lbl.setFont(_font(10))
        update_lbl.setStyleSheet(
            f"color:{C['accent_dim']}; text-decoration:underline;"
        )
        update_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        fl.addWidget(ver_lbl)
        fl.addWidget(update_lbl)
        root.addWidget(footer)

        # Activate first item
        self._activate("projects")

    def _on_nav_clicked(self, key: str):
        self._activate(key)
        self.nav_changed.emit(key)

    def _activate(self, key: str):
        for k, item in self._items.items():
            item.set_active(k == key)


# ── Top bar ────────────────────────────────────────────────────────────────────

class TopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet(
            f"background:{C['bg_content']};"
            f"border-bottom:1px solid {C['border']};"
        )
        self._build()

    def _build(self):
        ly = QHBoxLayout(self)
        ly.setContentsMargins(24, 0, 20, 0)
        ly.setSpacing(12)

        title = QLabel("Welcome to Workspace Manager")
        title.setFont(_font(14, bold=True))
        title.setStyleSheet(f"color:{C['text_hi']}; border:none;")
        ly.addWidget(title)
        ly.addStretch()

        # Notification dot
        notif = QLabel("● 2 updates available")
        notif.setFont(_font(11))
        notif.setStyleSheet(
            f"color:{C['accent']}; border:none;"
        )
        ly.addWidget(notif)

        settings_btn = _SecondaryButton("⚙  Settings")
        settings_btn.setFixedWidth(110)
        ly.addWidget(settings_btn)


# ── Main welcome window ────────────────────────────────────────────────────────

class WelcomeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Workspace Manager")
        self.setMinimumSize(900, 580)
        self.resize(1020, 640)
        self.setStyleSheet(f"background:{C['bg_content']};")
        self._build()
        self._fade_in()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        self._sidebar.nav_changed.connect(self._on_nav)
        root.addWidget(self._sidebar)

        # Vertical rule
        root.addWidget(_Divider(vertical=True))

        # Right: top bar + stacked content
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        self._top_bar = TopBar()
        right.addWidget(self._top_bar)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{C['bg_content']};")

        self._panels = {
            "projects":  ProjectsPanel(),
            "customize": CustomizePanel(),
            "plugins":   PluginsPanel(),
            "learn":     LearnPanel(),
        }
        for panel in self._panels.values():
            panel.setStyleSheet(f"background:{C['bg_content']};")
            self._stack.addWidget(panel)

        right.addWidget(self._stack, stretch=1)

        right_container = QWidget()
        right_container.setLayout(right)
        root.addWidget(right_container, stretch=1)

    def _on_nav(self, key: str):
        panel = self._panels.get(key)
        if panel:
            self._stack.setCurrentWidget(panel)

    def _fade_in(self):
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Workspace Manager")

    # Apply base palette so Qt's internal widgets don't flash white
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window,     QColor(C["bg_content"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(C["text_hi"]))
    pal.setColor(QPalette.ColorRole.Base,       QColor(C["bg_card"]))
    pal.setColor(QPalette.ColorRole.Text,       QColor(C["text_hi"]))
    pal.setColor(QPalette.ColorRole.Highlight,  QColor(C["accent"]))
    app.setPalette(pal)

    win = WelcomeWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()