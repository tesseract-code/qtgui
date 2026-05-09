from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QToolBar, QLabel, QToolButton

from qtgui.icons import _get_line_icon


class ModelToolBar(QToolBar):
    """Toolbar for the model viewer, emitting high‑level signals."""

    openRequested = pyqtSignal()
    exportRequested = pyqtSignal()
    resetCameraRequested = pyqtSignal()
    wireframeToggled = pyqtSignal(bool)
    gridToggled = pyqtSignal(bool)
    backgroundChangeRequested = pyqtSignal()
    lightingRequested = pyqtSignal()
    statisticsRequested = pyqtSignal()
    screenshotRequested = pyqtSignal()
    undoRequested = pyqtSignal()
    redoRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Main Toolbar", parent)
        self._status_label = QLabel("Ready")
        self._wire_btn = QToolButton()
        self._grid_btn = QToolButton()
        self._build_ui()

    def _build_ui(self):
        # Helper to create a tool button
        def _btn(label, slot, icon_name):
            b = QToolButton()
            b.setToolTip(label)
            b.setIcon(_get_line_icon(icon_name, color=self.palette().accent().color()))
            b.clicked.connect(slot)
            self.addWidget(b)
            return b

        _btn("Open", self.openRequested.emit, "file-add-line")
        _btn("Export", self.exportRequested.emit, "export-line")
        self.addSeparator()
        _btn("Reset Camera", self.resetCameraRequested.emit,
             "camera-switch-line")

        self._wire_btn.setCheckable(True)
        self._wire_btn.setIcon(
            _get_line_icon("global-line",
                           color=self.palette().accent().color()))
        self._wire_btn.setToolTip("Toggle wireframe/solid")
        self._wire_btn.toggled.connect(self.wireframeToggled.emit)
        self.addWidget(self._wire_btn)

        self._grid_btn.setCheckable(True)
        self._grid_btn.setIcon(
            _get_line_icon("grid-line",
                           color=self.palette().accent().color()))
        self._grid_btn.setToolTip("Toggle bounding-box grid")
        self._grid_btn.toggled.connect(self.gridToggled.emit)
        self.addWidget(self._grid_btn)

        _btn("Background", self.backgroundChangeRequested.emit,"multi-image-line")
        self.addSeparator()
        _btn("Lighting", self.lightingRequested.emit,"lightbulb-line")
        _btn("Statistics", self.statisticsRequested.emit,"donut-chart-line")
        _btn("Screenshot", self.screenshotRequested.emit,"camera-lens-line")
        self.addSeparator()
        _btn("Undo", self.undoRequested.emit,"arrow-go-back-line")
        _btn("Redo", self.redoRequested.emit,"arrow-go-forward-line")
        self.addSeparator()
        self.addWidget(self._status_label)

    @ property
    def wire_btn(self) -> QToolButton:
        return self._wire_btn

    @property
    def grid_btn(self) -> QToolButton:
        return self._grid_btn

    @property
    def status_label(self) -> QLabel:
        return self._status_label
