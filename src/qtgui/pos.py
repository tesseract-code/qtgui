#!/usr/bin/env python3
"""
3D Positioner — XYZUVW Object Pose Viewer
==========================================
Drag viewport to orbit camera. Scroll to zoom.
X/Y/Z  = position  |  U/V/W = roll/pitch/yaw (degrees)

Requirements:
    pip install PyQt6 numpy
"""

import sys
import math
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QGridLayout, QLabel, QSlider, QDoubleSpinBox, QGroupBox,
    QPushButton, QFrame, QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QFont,
    QPolygonF, QFontDatabase, QPainterPath, QRadialGradient, QConicalGradient
)

# ── Palette ────────────────────────────────────────────────────────────────────
BG_DARK       = QColor(10,  12,  20)
BG_PANEL      = QColor(18,  20,  32)
BG_CARD       = QColor(24,  27,  42)
BORDER        = QColor(45,  50,  80)
ACCENT        = QColor(0,  200, 160)
ACCENT2       = QColor(80, 120, 255)
TEXT_BRIGHT   = QColor(220, 225, 255)
TEXT_DIM      = QColor(100, 110, 150)

AX_X = QColor(255,  70,  70)   # world X — red
AX_Y = QColor( 70, 220,  70)   # world Y — green
AX_Z = QColor( 70, 130, 255)   # world Z — blue
OBJ_U = QColor(255, 130, 130)  # object U (roll  axis)
OBJ_V = QColor(130, 255, 130)  # object V (pitch axis)
OBJ_W = QColor(130, 180, 255)  # object W (yaw   axis)
GRID_MAJOR = QColor(40, 45, 70)
GRID_MINOR = QColor(28, 32, 50)


# ── 3D Viewport ────────────────────────────────────────────────────────────────
class Viewport3D(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 440)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Camera state
        self.cam_az   = 35.0   # azimuth  (°)
        self.cam_el   = 25.0   # elevation (°)
        self.cam_dist = 9.0

        # Object pose
        self.ox = self.oy = self.oz = 0.0   # position
        self.ou = self.ov = self.ow = 0.0   # rotation (roll, pitch, yaw) °

        self._drag_pos  = None
        self._trail: list[np.ndarray] = []

    # ── pose setter ────────────────────────────────────────────────────────────
    def set_pose(self, x, y, z, u, v, w):
        prev = np.array([self.ox, self.oy, self.oz])
        self.ox, self.oy, self.oz = x, y, z
        self.ou, self.ov, self.ow = u, v, w
        cur = np.array([x, y, z])
        if np.linalg.norm(cur - prev) > 0.05:
            self._trail.append(cur.copy())
            if len(self._trail) > 80:
                self._trail.pop(0)
        self.update()

    def reset_pose(self):
        self.ox = self.oy = self.oz = 0.0
        self.ou = self.ov = self.ow = 0.0
        self._trail.clear()
        self.update()

    # ── projection ─────────────────────────────────────────────────────────────
    def _camera_basis(self):
        az = math.radians(self.cam_az)
        el = math.radians(self.cam_el)
        d  = self.cam_dist
        cam_pos = np.array([
            d * math.cos(el) * math.cos(az),
            d * math.cos(el) * math.sin(az),
            d * math.sin(el)
        ])
        fwd   = -cam_pos / np.linalg.norm(cam_pos)
        world_up = np.array([0., 0., 1.])
        right = np.cross(fwd, world_up)
        if np.linalg.norm(right) < 1e-6:
            world_up = np.array([0., 1., 0.])
            right = np.cross(fwd, world_up)
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        return cam_pos, fwd, right, up

    def project(self, pt3, W, H):
        cam_pos, fwd, right, up = self._camera_basis()
        p = np.asarray(pt3, dtype=float) - cam_pos
        rx = np.dot(p, right)
        ry = np.dot(p, up)
        rz = np.dot(p, fwd)
        if rz <= 0.001:
            return None
        fov_f  = 1.0 / math.tan(math.radians(55) / 2)
        aspect = W / H
        sx = fov_f * rx / rz / aspect
        sy = fov_f * ry / rz
        return ((sx + 1) * W / 2, (1 - sy) * H / 2)

    # ── rotation matrix (ZYX Tait-Bryan) ──────────────────────────────────────
    @staticmethod
    def rot_matrix(u_deg, v_deg, w_deg):
        u, v, w = map(math.radians, [u_deg, v_deg, w_deg])
        Rx = np.array([[1,0,0],[0,math.cos(u),-math.sin(u)],[0,math.sin(u),math.cos(u)]])
        Ry = np.array([[math.cos(v),0,math.sin(v)],[0,1,0],[-math.sin(v),0,math.cos(v)]])
        Rz = np.array([[math.cos(w),-math.sin(w),0],[math.sin(w),math.cos(w),0],[0,0,1]])
        return Rz @ Ry @ Rx

    # ── draw helpers ───────────────────────────────────────────────────────────
    def _arrow(self, painter, a3, b3, color, lw, label, W, H, tip=12):
        p1 = self.project(a3, W, H)
        p2 = self.project(b3, W, H)
        if not p1 or not p2:
            return
        pen = QPen(color, lw, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(*p1), QPointF(*p2))
        # arrowhead
        dx, dy = p2[0]-p1[0], p2[1]-p1[1]
        L = math.hypot(dx, dy)
        if L > 1:
            dx, dy = dx/L, dy/L
            w = tip * 0.45
            ax1 = QPointF(p2[0] - tip*dx + w*(-dy), p2[1] - tip*dy + w*dx)
            ax2 = QPointF(p2[0] - tip*dx - w*(-dy), p2[1] - tip*dy - w*dx)
            poly = QPolygonF([QPointF(*p2), ax1, ax2])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawPolygon(poly)
        if label:
            painter.setPen(QPen(color))
            f = QFont("Courier New", 8, QFont.Weight.Bold)
            painter.setFont(f)
            painter.drawText(QPointF(p2[0]+6, p2[1]+6), label)

    def _line(self, painter, a3, b3, color, lw, style, W, H):
        p1 = self.project(a3, W, H)
        p2 = self.project(b3, W, H)
        if not p1 or not p2:
            return
        painter.setPen(QPen(color, lw, style))
        painter.drawLine(QPointF(*p1), QPointF(*p2))

    # ── paint ──────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # Background
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0, QColor(10, 12, 22))
        grad.setColorAt(1, QColor(14, 18, 34))
        painter.fillRect(0, 0, W, H, grad)

        # ── Grid ──────────────────────────────────────────────────────────────
        GR = 5
        for i in range(-GR, GR+1):
            col = GRID_MAJOR if i % 5 == 0 else GRID_MINOR
            lw  = 1.2 if i % 5 == 0 else 0.6
            self._line(painter, [i,-GR,0],[i,GR,0],  col, lw, Qt.PenStyle.SolidLine, W, H)
            self._line(painter, [-GR,i,0],[GR,i,0],  col, lw, Qt.PenStyle.SolidLine, W, H)

        # ── World axes (origin) ───────────────────────────────────────────────
        L = 1.6
        self._arrow(painter, [0,0,0],[L,0,0], AX_X, 2, "X", W, H)
        self._arrow(painter, [0,0,0],[0,L,0], AX_Y, 2, "Y", W, H)
        self._arrow(painter, [0,0,0],[0,0,L], AX_Z, 2, "Z", W, H)

        # ── Trail ─────────────────────────────────────────────────────────────
        for i in range(1, len(self._trail)):
            a, b = self._trail[i-1], self._trail[i]
            alpha = int(60 * i / len(self._trail))
            c = QColor(0, 200, 160, alpha)
            self._line(painter, a, b, c, 1.5, Qt.PenStyle.SolidLine, W, H)

        # ── Object dashed line from origin ────────────────────────────────────
        obj = np.array([self.ox, self.oy, self.oz])
        self._line(painter, [0,0,0], obj, QColor(150,150,180,70), 1,
                   Qt.PenStyle.DashLine, W, H)

        # ── Shadow dot on Z=0 plane ────────────────────────────────────────────
        sh = self.project([self.ox, self.oy, 0], W, H)
        if sh:
            self._line(painter, [self.ox,self.oy,0], obj,
                       QColor(120,130,160,50), 1, Qt.PenStyle.DotLine, W, H)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 200, 160, 40)))
            painter.drawEllipse(QPointF(*sh), 6, 3)

        # ── Object triad ───────────────────────────────────────────────────────
        R  = self.rot_matrix(self.ou, self.ov, self.ow)
        AL = 1.0
        ux = obj + R @ np.array([AL, 0, 0])
        vy = obj + R @ np.array([0, AL, 0])
        wz = obj + R @ np.array([0, 0, AL])
        self._arrow(painter, obj, ux, OBJ_U, 3, "U", W, H)
        self._arrow(painter, obj, vy, OBJ_V, 3, "V", W, H)
        self._arrow(painter, obj, wz, OBJ_W, 3, "W", W, H)

        # ── Object glow sphere ─────────────────────────────────────────────────
        po = self.project(obj, W, H)
        if po:
            rg = QRadialGradient(QPointF(*po), 18)
            rg.setColorAt(0, QColor(0, 220, 170, 160))
            rg.setColorAt(0.4, QColor(0, 200, 160, 60))
            rg.setColorAt(1, QColor(0, 200, 160, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(rg))
            painter.drawEllipse(QPointF(*po), 18, 18)

            painter.setPen(QPen(QColor(0, 230, 180), 2))
            painter.setBrush(QBrush(QColor(0, 200, 160, 100)))
            painter.drawEllipse(QPointF(*po), 7, 7)

        # ── HUD ───────────────────────────────────────────────────────────────
        self._draw_hud(painter, W, H)

    def _draw_hud(self, painter, W, H):
        # Coordinate readout box
        rows = [
            ("X", f"{self.ox:+8.3f}", AX_X),
            ("Y", f"{self.oy:+8.3f}", AX_Y),
            ("Z", f"{self.oz:+8.3f}", AX_Z),
            ("U", f"{self.ou:+8.2f}°", OBJ_U),
            ("V", f"{self.ov:+8.2f}°", OBJ_V),
            ("W", f"{self.ow:+8.2f}°", OBJ_W),
        ]
        bx, by, bw, bh = 12, 12, 178, 135
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(10, 12, 26, 190)))
        painter.drawRoundedRect(bx, by, bw, bh, 6, 6)
        painter.setPen(QPen(BORDER, 1))
        painter.drawRoundedRect(bx, by, bw, bh, 6, 6)

        font_lbl = QFont("Courier New", 8, QFont.Weight.Bold)
        font_val = QFont("Courier New", 9)
        for i, (name, val, col) in enumerate(rows):
            y = by + 22 + i * 19
            painter.setFont(font_lbl)
            painter.setPen(QPen(col))
            painter.drawText(bx + 12, y, name)
            painter.setFont(font_val)
            painter.setPen(QPen(TEXT_BRIGHT))
            painter.drawText(bx + 30, y, val)

        # Camera hint strip
        painter.setPen(QPen(TEXT_DIM))
        f = QFont("Courier New", 7)
        painter.setFont(f)
        hint = f"Az {self.cam_az:+.0f}°  El {self.cam_el:+.0f}°  D {self.cam_dist:.1f}  |  drag·orbit  scroll·zoom"
        painter.drawText(10, H - 8, hint)

    # ── Mouse / Scroll ─────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseMoveEvent(self, e):
        if self._drag_pos:
            d = e.position() - self._drag_pos
            self.cam_az  -= d.x() * 0.35
            self.cam_el   = max(-89, min(89, self.cam_el + d.y() * 0.35))
            self._drag_pos = e.position()
            self.update()

    def wheelEvent(self, e):
        self.cam_dist = max(2.5, min(40, self.cam_dist - e.angleDelta().y() * 0.012))
        self.update()


# ── Axis Control Row ───────────────────────────────────────────────────────────
class AxisControl(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, name: str, color: QColor,
                 lo: float, hi: float, unit: str = ""):
        super().__init__()
        self._unit = unit
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(8)

        # Axis label pill
        lbl = QLabel(name)
        lbl.setFixedWidth(28)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"""
            QLabel {{
                background: {color.name()};
                color: #fff;
                border-radius: 4px;
                font-family: 'Courier New';
                font-weight: bold;
                font-size: 11px;
                padding: 1px 4px;
            }}
        """)

        # Slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(lo * 100), int(hi * 100))
        self.slider.setValue(0)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px;
                background: #1e2238;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px; height: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: {color.name()};
                border: 2px solid #fff3;
            }}
            QSlider::sub-page:horizontal {{
                background: {color.name()}88;
                border-radius: 2px;
            }}
        """)

        # Spinbox
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(0.1)
        self.spin.setDecimals(3)
        self.spin.setFixedWidth(88)
        self.spin.setSuffix(f" {unit}" if unit else "")
        self.spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                background: #0e1020;
                color: {color.lighter(160).name()};
                border: 1px solid #2d3250;
                border-radius: 4px;
                padding: 2px 4px;
                font-family: 'Courier New';
                font-size: 10px;
            }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                width: 14px;
                background: #1a1e36;
                border: none;
            }}
        """)

        layout.addWidget(lbl)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)

        # Wire
        self.slider.valueChanged.connect(
            lambda v: (self.spin.blockSignals(True),
                       self.spin.setValue(v / 100),
                       self.spin.blockSignals(False),
                       self.valueChanged.emit(v / 100)))
        self.spin.valueChanged.connect(
            lambda v: (self.slider.blockSignals(True),
                       self.slider.setValue(int(v * 100)),
                       self.slider.blockSignals(False),
                       self.valueChanged.emit(v)))

    def value(self) -> float:
        return self.spin.value()

    def reset(self):
        self.spin.setValue(0.0)


# ── Control Panel ──────────────────────────────────────────────────────────────
class ControlPanel(QWidget):
    poseChanged = pyqtSignal(float, float, float, float, float, float)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(320)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Title
        title = QLabel("3D POSITIONER")
        title.setStyleSheet("""
            font-family: 'Courier New';
            font-size: 15px;
            font-weight: bold;
            color: #00c8a0;
            letter-spacing: 3px;
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        sub = QLabel("XYZUVW  ·  6 DOF  POSE  CONTROL")
        sub.setStyleSheet("""
            font-family: 'Courier New';
            font-size: 8px;
            color: #5a6080;
            letter-spacing: 2px;
        """)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(sub)

        self._sep(root)

        # Position group
        pos_box = self._group("POSITION", root)
        self.ctrl_x = AxisControl("X", AX_X,  -5.0, 5.0)
        self.ctrl_y = AxisControl("Y", AX_Y,  -5.0, 5.0)
        self.ctrl_z = AxisControl("Z", AX_Z,  -5.0, 5.0)
        pos_box.addWidget(self.ctrl_x)
        pos_box.addWidget(self.ctrl_y)
        pos_box.addWidget(self.ctrl_z)

        # Orientation group
        ori_box = self._group("ORIENTATION  ( U=roll  V=pitch  W=yaw )", root)
        self.ctrl_u = AxisControl("U", OBJ_U, -180.0, 180.0, "°")
        self.ctrl_v = AxisControl("V", OBJ_V, -180.0, 180.0, "°")
        self.ctrl_w = AxisControl("W", OBJ_W, -180.0, 180.0, "°")
        ori_box.addWidget(self.ctrl_u)
        ori_box.addWidget(self.ctrl_v)
        ori_box.addWidget(self.ctrl_w)

        self._sep(root)

        # Readout box
        self._readout_labels = {}
        ro_box = self._group("LIVE READOUT", root)
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (name, col) in enumerate([("X", AX_X), ("Y", AX_Y), ("Z", AX_Z),
                                          ("U", OBJ_U), ("V", OBJ_V), ("W", OBJ_W)]):
            row, col_idx = divmod(i, 3)
            lbl = QLabel(f"{name}")
            lbl.setStyleSheet(f"color:{col.name()};font-family:'Courier New';font-size:8px;font-weight:bold;")
            val = QLabel("  0.000")
            val.setStyleSheet("color:#c8d0ff;font-family:'Courier New';font-size:9px;")
            grid.addWidget(lbl, row*2,   col_idx)
            grid.addWidget(val, row*2+1, col_idx)
            self._readout_labels[name] = val
        ro_box.addLayout(grid)

        self._sep(root)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_reset = self._button("RESET", "#c0392b")
        self.btn_home  = self._button("HOME",  "#1a6fa0")
        btn_row.addWidget(self.btn_reset)
        btn_row.addWidget(self.btn_home)
        root.addLayout(btn_row)

        root.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                                        QSizePolicy.Policy.Expanding))

        # Wire all controls
        for ctrl in [self.ctrl_x, self.ctrl_y, self.ctrl_z,
                     self.ctrl_u, self.ctrl_v, self.ctrl_w]:
            ctrl.valueChanged.connect(self._emit)

        self.btn_reset.clicked.connect(self._reset)
        self.btn_home.clicked.connect(self._home)

    # ── helpers ────────────────────────────────────────────────────────────────
    def _group(self, title, parent_layout) -> QVBoxLayout:
        box = QGroupBox(title)
        box.setStyleSheet("""
            QGroupBox {
                color: #5a6080;
                border: 1px solid #2d3250;
                border-radius: 6px;
                margin-top: 8px;
                font-family: 'Courier New';
                font-size: 8px;
                letter-spacing: 1px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px; padding: 0 4px;
            }
        """)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(4, 10, 4, 6)
        layout.setSpacing(2)
        parent_layout.addWidget(box)
        return layout

    def _sep(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2d3250;")
        layout.addWidget(line)

    def _button(self, text, bg) -> QPushButton:
        b = QPushButton(text)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: #fff;
                border: none;
                border-radius: 5px;
                padding: 7px 14px;
                font-family: 'Courier New';
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 2px;
            }}
            QPushButton:hover  {{ background: {QColor(bg).lighter(130).name()}; }}
            QPushButton:pressed {{ background: {QColor(bg).darker(120).name()}; }}
        """)
        return b

    def _emit(self):
        x, y, z = self.ctrl_x.value(), self.ctrl_y.value(), self.ctrl_z.value()
        u, v, w = self.ctrl_u.value(), self.ctrl_v.value(), self.ctrl_w.value()
        self._readout_labels["X"].setText(f"{x:+.3f}")
        self._readout_labels["Y"].setText(f"{y:+.3f}")
        self._readout_labels["Z"].setText(f"{z:+.3f}")
        self._readout_labels["U"].setText(f"{u:+.2f}°")
        self._readout_labels["V"].setText(f"{v:+.2f}°")
        self._readout_labels["W"].setText(f"{w:+.2f}°")
        self.poseChanged.emit(x, y, z, u, v, w)

    def _reset(self):
        for ctrl in [self.ctrl_x, self.ctrl_y, self.ctrl_z,
                     self.ctrl_u, self.ctrl_v, self.ctrl_w]:
            ctrl.reset()

    def _home(self):
        # Move to a sample "home" position
        self.ctrl_x.spin.setValue(1.0)
        self.ctrl_y.spin.setValue(1.0)
        self.ctrl_z.spin.setValue(1.0)
        self.ctrl_u.spin.setValue(0.0)
        self.ctrl_v.spin.setValue(0.0)
        self.ctrl_w.spin.setValue(0.0)


# ── Main Window ────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Positioner — XYZUVW")
        self.resize(960, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.viewport = Viewport3D()
        self.panel    = ControlPanel()

        # Panel styling
        self.panel.setStyleSheet(f"background: {BG_PANEL.name()};")
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {BORDER.name()};")

        layout.addWidget(self.panel)
        layout.addWidget(sep)
        layout.addWidget(self.viewport, 1)

        self.panel.poseChanged.connect(self.viewport.set_pose)
        self.panel.btn_reset.clicked.connect(self.viewport.reset_pose)

        self.setStyleSheet(f"QMainWindow {{ background: {BG_DARK.name()}; }}")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Force dark palette
    from PyQt6.QtGui import QPalette
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          BG_DARK)
    pal.setColor(QPalette.ColorRole.WindowText,      TEXT_BRIGHT)
    pal.setColor(QPalette.ColorRole.Base,            BG_CARD)
    pal.setColor(QPalette.ColorRole.AlternateBase,   BG_PANEL)
    pal.setColor(QPalette.ColorRole.Text,            TEXT_BRIGHT)
    pal.setColor(QPalette.ColorRole.Button,          BG_PANEL)
    pal.setColor(QPalette.ColorRole.ButtonText,      TEXT_BRIGHT)
    pal.setColor(QPalette.ColorRole.Highlight,       ACCENT)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())