from enum import unique, StrEnum
from typing import Dict

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (QWidget, QRadioButton, QVBoxLayout, QGroupBox,
                             QButtonGroup, QGridLayout, QPushButton, QLabel,
                             QDoubleSpinBox, QSpinBox,
                             QSlider, QTextEdit)


@unique
class AnalysisMode(StrEnum):
    """Enumeration of available AM analysis modes."""
    NONE = "none"
    OVERHANG = "overhang"
    WALL = "wall"
    LAYER = "layer"
    SUPPORT = "support"


class AnalysisPanel(QWidget):
    """Right‑hand analysis panel. Exposes child widgets for backward compatibility."""

    modeChanged = pyqtSignal(object)  # AnalysisMode
    buildDirectionChanged = pyqtSignal(tuple)  # (x, y, z)
    overhangThresholdChanged = pyqtSignal()
    layerThicknessChanged = pyqtSignal(int)
    layerSliderChanged = pyqtSignal(int)
    minWallChanged = pyqtSignal()
    meshCheckRequested = pyqtSignal()
    modeRadioButtons: Dict[AnalysisMode, QRadioButton]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.modeChanged.connect(lambda _: None)
        self._build_ui()

    # ------------------------------------------------------------------
    # Build helpers (each creates one logical group)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Assemble the panel from individual groups."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        layout.addWidget(self._build_analysis_mode_group())
        layout.addWidget(self._build_direction_group())
        layout.addWidget(self._build_overhang_group())
        layout.addWidget(self._build_layer_group())
        layout.addWidget(self._build_wall_group())
        layout.addWidget(self._build_mesh_group())
        layout.addStretch()

    def _build_analysis_mode_group(self) -> QGroupBox:
        group = QGroupBox("Analysis Mode")
        mode_layout = QVBoxLayout(group)
        mode_layout.setSpacing(10)
        self._mode_btn_group = QButtonGroup(self)
        self.modeRadioButtons = {}
        for label, mode in [
            ("None", AnalysisMode.NONE),
            ("Overhang Heat Map", AnalysisMode.OVERHANG),
            ("Wall Thickness", AnalysisMode.WALL),
            ("Layer Preview", AnalysisMode.LAYER),
            ("Support Estimate", AnalysisMode.SUPPORT),
        ]:
            rb = QRadioButton(label)
            if mode == AnalysisMode.NONE:
                rb.setChecked(True)
            self._mode_btn_group.addButton(rb)
            mode_layout.addWidget(rb)
            rb.clicked.connect(lambda checked, m=mode: self.modeChanged.emit(m))
            self.modeRadioButtons[mode] = rb
        return group

    def _build_direction_group(self) -> QGroupBox:
        group = QGroupBox("Build Direction")
        dir_grid = QGridLayout(group)
        self._dir_button_group = QButtonGroup(self)
        self._dir_button_group.setExclusive(True)
        self._dir_buttons = {}
        directions = [
            ("+X", (1, 0, 0)), ("-X", (-1, 0, 0)),
            ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0)),
            ("+Z", (0, 0, 1)), ("-Z", (0, 0, -1)),
        ]
        for col, (dlbl, vec) in enumerate(directions):
            row, c = divmod(col, 2)
            btn = QPushButton(dlbl)
            btn.setCheckable(True)
            self._dir_button_group.addButton(btn)
            self._dir_buttons[vec] = btn
            dir_grid.addWidget(btn, row, c)
        self._dir_button_group.buttonClicked.connect(
            self._on_dir_button_clicked)
        default_dir = (0, 0, 1)
        if default_dir in self._dir_buttons:
            self._dir_buttons[default_dir].setChecked(True)
        return group

    def _build_overhang_group(self) -> QGroupBox:
        group = QGroupBox("Overhang Settings")
        oh_layout = QGridLayout(group)
        oh_layout.addWidget(QLabel("Threshold (deg):"), 0, 0)
        self._overhang_spin = QDoubleSpinBox()
        self._overhang_spin.setRange(1.0, 89.0)
        self._overhang_spin.setValue(45.0)
        self._overhang_spin.setSingleStep(5.0)
        self._overhang_spin.setDecimals(1)
        self._overhang_spin.valueChanged.connect(
            self.overhangThresholdChanged.emit)
        oh_layout.addWidget(self._overhang_spin, 0, 1)
        return group

    def _build_layer_group(self) -> QGroupBox:
        group = QGroupBox("Layer Preview")
        layer_layout = QGridLayout(group)
        layer_layout.addWidget(QLabel("Thickness (um):"), 0, 0)
        self._layer_thickness_spin = QSpinBox()
        self._layer_thickness_spin.setRange(10, 500)
        self._layer_thickness_spin.setValue(50)
        self._layer_thickness_spin.setSuffix(" um")
        self._layer_thickness_spin.valueChanged.connect(
            lambda v: self.layerThicknessChanged.emit(v))
        layer_layout.addWidget(self._layer_thickness_spin, 0, 1)

        self._layer_slider = QSlider(Qt.Orientation.Horizontal)
        self._layer_slider.setRange(0, 0)
        self._layer_slider.setValue(0)
        self._layer_slider.valueChanged.connect(self.layerSliderChanged.emit)
        layer_layout.addWidget(self._layer_slider, 1, 0, 1, 2)

        self._layer_info_label = QLabel("Layer: - / -")
        layer_layout.addWidget(self._layer_info_label, 2, 0, 1, 2)
        self._layer_area_label = QLabel("Area: -")
        layer_layout.addWidget(self._layer_area_label, 3, 0, 1, 2)
        return group

    def _build_wall_group(self) -> QGroupBox:
        group = QGroupBox("Wall Thickness")
        wall_layout = QGridLayout(group)
        wall_layout.addWidget(QLabel("Min target (mm):"), 0, 0)
        self._min_wall_spin = QDoubleSpinBox()
        self._min_wall_spin.setRange(0.01, 50.0)
        self._min_wall_spin.setValue(0.5)
        self._min_wall_spin.setDecimals(2)
        self._min_wall_spin.setSingleStep(0.1)
        self._min_wall_spin.valueChanged.connect(self.minWallChanged.emit)
        wall_layout.addWidget(self._min_wall_spin, 0, 1)
        self._wall_progress_label = QLabel("")
        wall_layout.addWidget(self._wall_progress_label, 1, 0, 1, 2)
        return group

    def _build_mesh_group(self) -> QGroupBox:
        group = QGroupBox("Mesh Integrity")
        mesh_layout = QVBoxLayout(group)
        run_btn = QPushButton("Run Check")
        run_btn.clicked.connect(self.meshCheckRequested.emit)
        mesh_layout.addWidget(run_btn)
        self._mesh_result_edit = QTextEdit()
        self._mesh_result_edit.setReadOnly(True)
        self._mesh_result_edit.setMaximumHeight(110)
        self._mesh_result_edit.setPlainText("-")
        mesh_layout.addWidget(self._mesh_result_edit)
        return group

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------
    def _on_dir_button_clicked(self, button: QPushButton) -> None:
        """Emit the build direction when a direction button is clicked."""
        for vec, btn in self._dir_buttons.items():
            if btn is button:
                self.buildDirectionChanged.emit(vec)
                return

    # ------------------------------------------------------------------
    # Backward‑compatible property access
    # ------------------------------------------------------------------
    @property
    def overhang_spin(self) -> QDoubleSpinBox:
        return self._overhang_spin

    @property
    def layer_thickness_spin(self) -> QSpinBox:
        return self._layer_thickness_spin

    @property
    def layer_slider(self) -> QSlider:
        return self._layer_slider

    @property
    def layer_info_label(self) -> QLabel:
        return self._layer_info_label

    @property
    def layer_area_label(self) -> QLabel:
        return self._layer_area_label

    @property
    def min_wall_spin(self) -> QDoubleSpinBox:
        return self._min_wall_spin

    @property
    def wall_progress_label(self) -> QLabel:
        return self._wall_progress_label

    @property
    def mesh_result_edit(self) -> QTextEdit:
        return self._mesh_result_edit
