from math import pi, ceil
from typing import Optional

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot


class Spinner(QtWidgets.QWidget):
    """A circular spinner widget with no progress bar"""

    _start = pyqtSignal()
    _start_timeout = pyqtSignal(int)
    _stop = pyqtSignal()

    def __init__(self, center_on_parent=True, disable_parent=True,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.center = center_on_parent
        self.disable = disable_parent
        self._rotate_timer = QtCore.QTimer(self)
        self._rotate_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._display_timer = QtCore.QTimer()
        self._display_timer.setSingleShot(True)
        self._display_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._display_timer.timeout.connect(self.stop)
        self._is_spinning = False
        self._current_counter = 0
        self._spinner_color = QtGui.QColor(Qt.GlobalColor.gray)
        self._spinner_roundness = 100.0
        self._spinner_min_trail_opacity = pi * 10
        self._spinner_trail_fade_percentage = 50.0
        self._spinner_revs_per_sec = pi / 2
        self._spinner_num_spin_lines = 20
        self._spinner_line_length = 10
        self._spinner_line_width = 2
        self._spinner_inner_radius = 20
        self.init()

    def init(self):
        self._rotate_timer.timeout.connect(self.rotate)
        self._start.connect(self._start_spinner)
        self._start_timeout.connect(self._start_spinner)
        self._stop.connect(self._stop_spinner)
        self.update_size()
        self.update_timer()
        self.hide()

    @pyqtSlot()
    @pyqtSlot(int)
    def _start_spinner(self, timeout_ms: Optional[int] = None):
        self.update_pos()
        self._is_spinning = True
        self.show()

        if self.parentWidget() and self.disable:
            self.parentWidget().setEnabled(False)

        self.raise_()

        if not self._rotate_timer.isActive():
            self._rotate_timer.start()
            self._current_counter = 0

        if timeout_ms:
            self._display_timer.start(timeout_ms)

    @pyqtSlot()
    def _stop_spinner(self):
        self._is_spinning = False
        self.hide()

        if self.parentWidget() and self.disable:
            self.parentWidget().setEnabled(True)

        if self._rotate_timer.isActive():
            self._rotate_timer.stop()
            self._current_counter = 0

    @pyqtSlot()
    @pyqtSlot(int)
    def start(self, timeout_ms: Optional[int] = None):
        if timeout_ms:
            self._start_timeout.emit(timeout_ms)
        else:
            self._start.emit()

    @pyqtSlot()
    def stop(self):
        self._stop.emit()

    @pyqtSlot()
    def rotate(self):
        self._current_counter += 1
        if self._current_counter > self.num_spin_lines:
            self._current_counter = 0
        self.update()

    def update_size(self):
        size = (self._spinner_inner_radius + self._spinner_line_length) * 2
        self.setFixedSize(size, size)

    def update_timer(self):
        self._rotate_timer.setInterval(
            int(1000
                / (self._spinner_num_spin_lines * self._spinner_revs_per_sec)))

    def update_pos(self):
        if self.parentWidget() and self.center:
            parent_rect = self.parentWidget().rect()
            center = parent_rect.center()
            self.move(center.x() - self.width() // 2,
                      center.y() - self.height() // 2)

    def paintEvent(self, event):
        self.update_pos()
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        if self._current_counter > self._spinner_num_spin_lines:
            self._current_counter = 0
        painter.setPen(Qt.PenStyle.NoPen)

        for i in range(self._spinner_num_spin_lines):
            painter.save()
            painter.translate(self._spinner_inner_radius +
                              self._spinner_line_length,
                              self._spinner_inner_radius +
                              self._spinner_line_length)
            rotateAngle = 360.0 * i / self._spinner_num_spin_lines
            painter.rotate(rotateAngle)
            painter.translate(self._spinner_inner_radius, 0)
            distance = self.get_distance_from_primary(i,
                                                      self._current_counter,
                                                      self._spinner_num_spin_lines)
            color = self.get_current_line_color(distance,
                                                self._spinner_num_spin_lines,
                                                self._spinner_trail_fade_percentage,
                                                self._spinner_min_trail_opacity,
                                                self._spinner_color)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QtCore.QRect(0, -self._spinner_line_width // 2,
                             self._spinner_line_length,
                             self._spinner_line_length),
                self._spinner_roundness,
                self._spinner_roundness,
                Qt.SizeMode.RelativeSize
            )
            painter.restore()

    @staticmethod
    def get_distance_from_primary(current, primary, total_num_lines):
        distance = primary - current
        if distance < 0:
            distance += total_num_lines
        return distance

    def get_current_line_color(self, count_distance, total_num_lines,
                               trail_fade_pct,
                               min_opacity, color):
        if count_distance == 0:
            return color

        minAlphaF = min_opacity / 100.0

        distance_range = ceil((total_num_lines - 1) * trail_fade_pct / 100.0)
        if count_distance > distance_range:
            color.setAlphaF(minAlphaF)
        else:
            alphaDiff = self._spinner_color.alphaF() - minAlphaF
            gradient = alphaDiff / distance_range + 1.0
            resultAlpha = color.alphaF() - gradient * count_distance
            resultAlpha = min(1.0, max(0.0, resultAlpha))
            color.setAlphaF(resultAlpha)
        return color

    @property
    def color(self) -> QtGui.QColor:
        return self._spinner_color

    @color.setter
    def color(self, color: QtGui.QColor):
        self._spinner_color = color

    @property
    def roundness(self) -> float:
        return self._spinner_roundness

    @roundness.setter
    def roundness(self, roundness: float):
        self._spinner_roundness = max(0.0, min(100, int(roundness)))

    @property
    def min_trail_opacity(self) -> float:
        return self._spinner_min_trail_opacity

    @min_trail_opacity.setter
    def min_trail_opacity(self, trail_opacity: float):
        self._spinner_min_trail_opacity = trail_opacity

    @property
    def trail_fade_percentage(self) -> float:
        return self._spinner_trail_fade_percentage

    @trail_fade_percentage.setter
    def trail_fade_percentage(self, trail: float):
        self._spinner_trail_fade_percentage = trail

    @property
    def revs_per_sec(self):
        return self._spinner_revs_per_sec

    @revs_per_sec.setter
    def revs_per_sec(self, revs_per_sec: float):
        self._spinner_revs_per_sec = revs_per_sec
        self.update_timer()

    @property
    def num_spin_lines(self) -> int:
        return self._spinner_num_spin_lines

    @num_spin_lines.setter
    def num_spin_lines(self, lines: int):
        self._spinner_num_spin_lines = lines
        self.update_timer()

    @property
    def line_length(self) -> int:
        return self._spinner_line_length

    @line_length.setter
    def line_length(self, length: int):
        self._spinner_line_length = length
        self.update_size()

    @property
    def line_width(self) -> int:
        return self._spinner_line_width

    @line_width.setter
    def line_width(self, width: int):
        self._spinner_line_width = width
        self.update_size()

    @property
    def inner_radius(self) -> int:
        return self._spinner_inner_radius

    @inner_radius.setter
    def inner_radius(self, radius: int):
        self._spinner_inner_radius = radius
        self.update_size()

    @property
    def is_spinning(self):
        return self._is_spinning
