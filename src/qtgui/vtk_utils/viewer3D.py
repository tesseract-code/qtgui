"""
Embeddable 3D Model Viewer Widget for PyQt6.

Public API
----------
configure_surface_format()
    Must be called **before** ``QApplication`` is instantiated.

ModelViewerWidget
    Drop-in ``QWidget`` subclass with a right-hand AM analysis panel.

    Additional methods
    ------------------
    show_grid(visible: bool)
        Show or hide a bounding-box grid around the model.
    toggle_grid()
        Toggle grid visibility on/off.
    load_model(path, *, add_undo=True) -> bool
    clear_model()
    reset_camera()
    undo() / redo()

    show_build_plate(visible: bool)
        Show/hide a translucent build plate at the model's base.
    enter_bc_mode() / exit_bc_mode()
        Interactive boundary condition assignment.
    assign_boundary_condition(cell_id, bc_type)
        Manually assign a BC type (1=Fix,2=Heat,3=Pressure) to a cell.
    clear_boundary_conditions()
        Remove all BC assignments.
    export_boundary_conditions(filepath) / import_boundary_conditions(filepath)
        Save/load BC assignments as JSON.

AM features
-----------
1. Mesh Integrity Check
2. Overhang Heat Map
3. Layer Preview
4. Support Volume Estimate
5. Wall Thickness Map
6. Boundary Condition Assignment

Supported file formats
----------------------
Read
    STL, OBJ, PLY, VTP, VTK, CASE (EnSight Gold)

Write
    STL, OBJ, PLY, VTK
"""

__all__ = ["ModelViewerWidget"]

import json
import logging
import math
import os
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QAction
from PyQt6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QMenu,
)
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkLookupTable
from vtkmodules.vtkCommonDataModel import vtkPlane, vtkPolyData
from vtkmodules.vtkFiltersCore import (
    vtkAppendPolyData,
    vtkCutter,
    vtkFeatureEdges,
    vtkTriangleFilter,
)
from vtkmodules.vtkFiltersGeneral import vtkContourTriangulator
from vtkmodules.vtkFiltersSources import vtkPlaneSource
from vtkmodules.vtkIOExport import vtkOBJExporter
from vtkmodules.vtkIOGeometry import vtkOBJReader, vtkSTLReader, vtkSTLWriter
from vtkmodules.vtkIOImage import vtkPNGWriter
from vtkmodules.vtkIOLegacy import vtkPolyDataReader, vtkPolyDataWriter
from vtkmodules.vtkIOPLY import vtkPLYReader, vtkPLYWriter
from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
from vtkmodules.vtkRenderingAnnotation import vtkScalarBarActor
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkWindowToImageFilter,
    vtkCellPicker,
)

from qtgui.pixmap import colorize_pixmap
from qtgui.vtk_utils.case_reader import CaseFileReader
from qtgui.vtk_utils.history import HistoryAction, HistoryManager
from qtgui.vtk_utils.render import OffscreenVTKWidget
from qtgui.vtk_utils.ui.analysis import AnalysisMode, AnalysisPanel
from qtgui.vtk_utils.ui.controls import ModelToolBar
from qtgui.vtk_utils.ui.lighting import LightingDialog
from qtgui.vtk_utils.ui.statistic import StatisticsDialog
from qtgui.vtk_utils.utils import (
    _apply_actor_props,
    _capture_actor_props,
    _compute_cell_angles,
    _extract_cells_by_mask,
    _make_overhang_lut,
    _make_wall_lut,
    _model_base_and_height,
)
from qtgui.vtk_utils.viewport import VTKViewport
from qtgui.vtk_utils.worker import WallThicknessWorker

logger = logging.getLogger(__name__)

# Maximum number of (build_direction -> (angles, dots)) entries to keep in the
# angle cache before evicting the least-recently-used entry.
_MAX_ANGLE_CACHE: int = 16

# How long (ms) to wait for the wall-thickness worker to stop during cleanup
# before giving up and logging a warning.
_WORKER_STOP_TIMEOUT_MS: int = 5_000


@contextmanager
def _blocked(widget):
    """
    Temporarily block Qt signals on a widget.

    Parameters
    ----------
    widget : QObject
        Qt object whose signals should be temporarily blocked.

    Yields
    ------
    QObject
        The same widget with signals blocked.

    Notes
    -----
    The previous signal-blocking state is restored when the context exits.
    """
    previous = widget.blockSignals(True)
    try:
        yield widget
    finally:
        widget.blockSignals(previous)


class ModelViewerWidget(QWidget):
    """
    Embeddable PyQt6 widget for interactive 3-D model viewing.

    Signals
    -------
    model_loaded : pyqtSignal
        Emitted with the absolute file path after a model loads successfully.
    model_cleared : pyqtSignal
        Emitted when the scene is cleared.
    """

    model_loaded = pyqtSignal(str)
    model_cleared = pyqtSignal()

    _MAX_HISTORY: int = 20

    _READERS: Dict[str, type] = {
        ".stl": vtkSTLReader,
        ".ply": vtkPLYReader,
        ".obj": vtkOBJReader,
        ".vtp": vtkXMLPolyDataReader,
        ".vtk": vtkPolyDataReader,
    }

    _FILTER_EXT: Dict[str, str] = {
        "*.stl": ".stl",
        "*.obj": ".obj",
        "*.ply": ".ply",
        "*.vtk": ".vtk",
    }

    def __init__(self, parent=None) -> None:
        """
        Initialize the model viewer widget.

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget.
        """
        super().__init__(parent)

        self._actor: Optional[vtkActor] = None
        self._mapper: Optional[vtkPolyDataMapper] = None
        self._plain_mapper: Optional[vtkPolyDataMapper] = None
        self._source_poly: Optional[vtkPolyData] = None
        self._current_file: Optional[str] = None

        self._undo_manager = HistoryManager(self._MAX_HISTORY)
        self._undo_stack = self._undo_manager.undo_stack
        self._redo_stack = self._undo_manager.redo_stack

        self._am_mode: AnalysisMode = AnalysisMode.NONE
        self._build_dir: Tuple[float, float, float] = (0.0, 0.0, 1.0)
        self._am_overlays: list[vtkActor] = []
        self._scalar_bar: Optional[vtkScalarBarActor] = None
        self._mesh_check_actor: Optional[vtkActor] = None
        self._wall_worker: Optional[WallThicknessWorker] = None

        # LRU cache: build_dir key -> (angles: float32 ndarray, dots: float64 ndarray)
        # Bounded to _MAX_ANGLE_CACHE entries; OrderedDict preserves insertion/access
        # order so we can evict the least-recently-used entry cheaply.
        self._angle_cache: OrderedDict[
            Tuple[float, float, float], Tuple[np.ndarray, np.ndarray]
        ] = OrderedDict()

        self._pending_layer_idx: Optional[int] = None
        self._layer_update_timer = QTimer(self)
        self._layer_update_timer.setSingleShot(True)
        self._layer_update_timer.timeout.connect(
            self._perform_layer_preview_update
        )

        self._grid_visible: bool = False
        self._restoring: bool = False
        self._viewport: Optional[VTKViewport] = None

        self._case_reader: Optional[CaseFileReader] = None
        self._case_time_steps: list[float] = []

        # Build plate
        self._build_plate_actor: Optional[vtkActor] = None

        # Boundary condition support
        self._bc_mode_active: bool = False
        self._bc_picker = vtkCellPicker()
        self._boundary_conditions: Dict[int, int] = {}  # cell_id -> bc_type
        self._bc_colormap = {
            1: (1.0, 0.2, 0.2),   # fixed support
            2: (0.2, 1.0, 0.2),   # heat flux
            3: (0.2, 0.2, 1.0)    # pressure
        }
        self._bc_names = {
            1: "Fixed Support",
            2: "Heat Flux",
            3: "Pressure"
        }
        self._bc_original_props: Optional[dict] = None

        self._setup_ui()
        self._init_vtk()
        self._install_picking()

    def _setup_ui(self) -> None:
        """
        Construct the Qt user interface and connect widget signals.
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(2)

        self._toolbar = ModelToolBar(self)
        root.addWidget(self._toolbar)

        self._toolbar.openRequested.connect(self.open_file)
        self._toolbar.exportRequested.connect(self._show_export_dialog)
        self._toolbar.resetCameraRequested.connect(self.reset_camera)
        self._toolbar.wireframeToggled.connect(self._toggle_wireframe)
        self._toolbar.gridToggled.connect(self.toggle_grid)
        self._toolbar.backgroundChangeRequested.connect(self._choose_background)
        self._toolbar.lightingRequested.connect(self._show_lighting_dialog)
        self._toolbar.statisticsRequested.connect(self._show_statistics_dialog)
        self._toolbar.screenshotRequested.connect(self._screenshot)
        self._toolbar.undoRequested.connect(self.undo)
        self._toolbar.redoRequested.connect(self.redo)

        # BC mode button
        self._bc_action = QAction("BC Mode", self)
        self._bc_action.setCheckable(True)
        self._bc_action.triggered.connect(self._toggle_bc_mode)
        self._toolbar.addAction(self._bc_action)

        # Build plate toggle
        self._plate_action = QAction("Build Plate", self)
        self._plate_action.setCheckable(True)
        self._plate_action.setChecked(True)
        self._plate_action.triggered.connect(
            lambda checked: self.show_build_plate(checked)
        )
        self._toolbar.addAction(self._plate_action)

        self._wire_btn = self._toolbar.wire_btn
        self._grid_btn = self._toolbar.grid_btn
        self._status_label = self._toolbar.status_label

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        self._vtk_widget = OffscreenVTKWidget(parent=self)
        self._viewport = VTKViewport(self._vtk_widget)
        splitter.addWidget(self._vtk_widget)

        self._analysis_panel = AnalysisPanel(self)
        splitter.addWidget(self._analysis_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, 240])

        self._analysis_panel.modeChanged.connect(
            lambda mode: self._set_analysis_mode(mode)
        )
        self._analysis_panel.buildDirectionChanged.connect(self._set_build_dir)
        self._analysis_panel.overhangThresholdChanged.connect(
            lambda: self._refresh_analysis_if(AnalysisMode.OVERHANG)
        )
        self._analysis_panel.layerThicknessChanged.connect(
            self._rebuild_layer_slider
        )
        self._analysis_panel.layerSliderChanged.connect(
            self._update_layer_preview
        )
        self._analysis_panel.minWallChanged.connect(
            lambda: self._set_analysis_mode(AnalysisMode.WALL)
        )
        self._analysis_panel.meshCheckRequested.connect(self._run_mesh_check)

        self.setAcceptDrops(True)

    def _init_vtk(self) -> None:
        """
        Initialize the VTK viewport.
        """
        try:
            self._viewport.initialize()
            self._grid_visible = False
        except Exception:
            logger.exception("VTK initialisation failed")
            self._set_status("VTK initialisation failed -- see log")

    def _install_picking(self) -> None:
        """Install event filter on the VTK render window to catch mouse clicks for BC mode."""
        self._vtk_widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj == self._vtk_widget and event.type() == event.Type.MouseButtonPress:
            if self._bc_mode_active and event.button() == Qt.MouseButton.LeftButton:
                self._pick_cell_at(event.pos())
                return True
            elif self._bc_mode_active and event.button() == Qt.MouseButton.RightButton:
                self._exit_bc_mode()
                return True
        return super().eventFilter(obj, event)

    def _pick_cell_at(self, pos) -> None:
        """Perform cell picking at the given widget position and open BC assignment menu."""
        renderer = self._viewport.renderer
        if not renderer:
            return
        # Convert Qt top-left to VTK bottom-left
        y = self._vtk_widget.height() - pos.y()
        self._bc_picker.Pick(pos.x(), y, 0, renderer)
        cell_id = self._bc_picker.GetCellId()
        if cell_id == -1:
            self._set_status("No cell picked.")
            return
        menu = QMenu(self)
        menu.addAction("Clear BC", lambda: self.assign_boundary_condition(cell_id, 0))
        for bc_type, name in self._bc_names.items():
            menu.addAction(name, lambda t=bc_type: self.assign_boundary_condition(cell_id, t))
        menu.exec(self._vtk_widget.mapToGlobal(pos))

    # ---------- Build plate methods ----------

    def show_build_plate(self, visible: bool) -> None:
        """Show or hide the translucent build plate."""
        if visible and self._build_plate_actor is None and self._source_poly is not None:
            self._create_build_plate()
        if self._build_plate_actor:
            self._build_plate_actor.SetVisibility(visible)
            self._render()
        # FIX: use _blocked context manager instead of manual blockSignals calls
        if hasattr(self, "_plate_action"):
            with _blocked(self._plate_action):
                self._plate_action.setChecked(visible)

    def _create_build_plate(self) -> None:
        """Create a plane actor representing the build plate positioned at the model's base."""
        if self._source_poly is None:
            return
        base_h, _ = _model_base_and_height(
            self._source_poly.GetBounds(), self._build_dir
        )
        bounds = self._source_poly.GetBounds()
        x_min, x_max = bounds[0], bounds[1]
        y_min, y_max = bounds[2], bounds[3]
        dx = x_max - x_min
        dy = y_max - y_min
        plate = vtkPlaneSource()
        plate.SetOrigin(x_min - 0.1 * dx, y_min - 0.1 * dy, base_h - 0.1)
        plate.SetPoint1(x_max + 0.1 * dx, y_min - 0.1 * dy, base_h - 0.1)
        plate.SetPoint2(x_min - 0.1 * dx, y_max + 0.1 * dy, base_h - 0.1)
        plate.Update()
        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(plate.GetOutputPort())
        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.7, 0.7, 0.7)
        actor.GetProperty().SetOpacity(0.4)
        actor.SetVisibility(True)
        self._viewport.add_actor(actor)
        self._build_plate_actor = actor

    # ---------- Boundary condition public API ----------

    def enter_bc_mode(self) -> None:
        """
        Activate interactive boundary condition assignment mode.

        Equivalent to checking the BC Mode toolbar button programmatically.
        The model actor will become semi-transparent and left-clicking on any
        face will open a menu to assign a BC type.  Right-clicking (or calling
        :meth:`exit_bc_mode`) ends the session.
        """
        self._bc_action.setChecked(True)
        self._enter_bc_mode()

    def exit_bc_mode(self) -> None:
        """
        Exit interactive boundary condition assignment mode.

        Restores the actor's original appearance and unchecks the toolbar
        button.  Safe to call even when BC mode is not currently active.
        """
        self._bc_action.setChecked(False)
        self._exit_bc_mode()

    # ---------- Boundary condition internal methods ----------

    def _toggle_bc_mode(self, checked: bool) -> None:
        if checked:
            self._enter_bc_mode()
        else:
            self._exit_bc_mode()

    def _enter_bc_mode(self) -> None:
        """Activate interactive boundary condition assignment mode."""
        if self._actor is None:
            self._set_status("Load a model first.")
            with _blocked(self._bc_action):
                self._bc_action.setChecked(False)
            return
        self._bc_mode_active = True
        self._set_status(
            "BC mode: click on a face to assign conditions. Right-click to exit."
        )
        self._bc_original_props = _capture_actor_props(self._actor)
        self._actor.GetProperty().SetOpacity(0.6)
        self._render()

    def _exit_bc_mode(self) -> None:
        """Exit interactive assignment mode and restore appearance."""
        if not self._bc_mode_active:
            return
        self._bc_mode_active = False
        if self._bc_original_props and self._actor is not None:
            _apply_actor_props(self._actor, self._bc_original_props)
        self._refresh_boundary_visualisation()
        self._set_status("BC assignment mode exited.")
        with _blocked(self._bc_action):
            self._bc_action.setChecked(False)

    def _refresh_boundary_visualisation(self) -> None:
        """Update the model colouring to show current BC assignments."""
        if self._source_poly is None or self._actor is None:
            return
        n_cells = self._source_poly.GetNumberOfCells()
        bc_scalars = np.zeros(n_cells, dtype=np.int32)
        for cell_id, bc_type in self._boundary_conditions.items():
            if 0 <= cell_id < n_cells:
                bc_scalars[cell_id] = bc_type
        n_colors = max(self._bc_colormap.keys()) + 1
        lut = vtkLookupTable()
        lut.SetNumberOfTableValues(n_colors)
        lut.SetTableValue(0, 0.6, 0.6, 0.6, 1.0)  # default gray
        for bc_type, rgb in self._bc_colormap.items():
            if bc_type < n_colors:
                lut.SetTableValue(bc_type, *rgb, 1.0)
        lut.Build()
        pd = vtkPolyData()
        pd.ShallowCopy(self._source_poly)
        scalars = numpy_to_vtk(bc_scalars, deep=True)
        scalars.SetName("BC_Type")
        pd.GetCellData().SetScalars(scalars)
        mapper = vtkPolyDataMapper()
        mapper.SetInputData(pd)
        mapper.SetScalarModeToUseCellData()
        mapper.SetLookupTable(lut)
        mapper.SetScalarRange(0, n_colors - 1)
        mapper.ScalarVisibilityOn()
        self._actor.SetMapper(mapper)
        self._mapper = mapper
        self._show_scalar_bar("Boundary Condition", lut)
        self._render()

    def assign_boundary_condition(self, cell_id: int, bc_type: int) -> None:
        """Assign a boundary condition type to a specific cell (bc_type=0 removes)."""
        if bc_type == 0:
            if cell_id in self._boundary_conditions:
                del self._boundary_conditions[cell_id]
        else:
            self._boundary_conditions[cell_id] = bc_type
        self._push_undo(
            f"Assign BC {self._bc_names.get(bc_type, bc_type)} to cell {cell_id}"
        )
        self._refresh_boundary_visualisation()

    def clear_boundary_conditions(self) -> None:
        """Remove all assigned boundary conditions."""
        if not self._boundary_conditions:
            return
        self._boundary_conditions.clear()
        self._push_undo("Clear all boundary conditions")
        self._refresh_boundary_visualisation()

    def export_boundary_conditions(self, filepath: str) -> None:
        """
        Save BC assignments as JSON.

        Parameters
        ----------
        filepath : str
            Destination path for the JSON file.

        Raises
        ------
        Nothing — errors are reported via the status bar and logged.
        """
        data = {
            "boundary_conditions": {
                str(k): v for k, v in self._boundary_conditions.items()
            },
            "colormap": self._bc_colormap,
            "build_direction": self._build_dir,
            "model_file": self._current_file,
        }
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            logger.exception("export_boundary_conditions: could not write %s", filepath)
            self._set_status(f"Export failed: could not write {filepath}")
            return
        self._set_status(f"BCs exported to {filepath}")

    def import_boundary_conditions(self, filepath: str) -> None:
        """
        Load BC assignments from JSON and refresh the visualisation.

        Cell IDs that fall outside the range of the currently loaded model are
        silently ignored and a warning is logged.

        Parameters
        ----------
        filepath : str
            Path to the JSON file produced by :meth:`export_boundary_conditions`.

        Raises
        ------
        Nothing — errors are reported via the status bar and logged.
        """
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except OSError:
            logger.exception("import_boundary_conditions: could not read %s", filepath)
            self._set_status(f"Import failed: could not read {filepath}")
            return
        except json.JSONDecodeError:
            logger.exception(
                "import_boundary_conditions: invalid JSON in %s", filepath
            )
            self._set_status(f"Import failed: {filepath} is not valid JSON")
            return

        raw: dict = data.get("boundary_conditions", {})
        n_cells = self._source_poly.GetNumberOfCells() if self._source_poly else 0
        valid: Dict[int, int] = {}
        skipped = 0
        for k, v in raw.items():
            try:
                cell_id = int(k)
            except ValueError:
                skipped += 1
                continue
            if n_cells > 0 and not (0 <= cell_id < n_cells):
                skipped += 1
                continue
            valid[cell_id] = int(v)

        if skipped:
            logger.warning(
                "import_boundary_conditions: skipped %d out-of-range or invalid "
                "cell IDs from %s (model has %d cells)",
                skipped,
                filepath,
                n_cells,
            )

        self._boundary_conditions = valid
        self._refresh_boundary_visualisation()
        status = f"BCs imported from {filepath}"
        if skipped:
            status += f" ({skipped} invalid cell ID(s) skipped)"
        self._set_status(status)

    # ---------- Snapshot / restore ----------

    def _snapshot(self, action: str) -> dict:
        """
        Create a history snapshot of the current viewer state.
        """
        snap: dict = {
            "action": action,
            "file": self._current_file,
            "background": tuple(
                self._viewport.get_background()
            ) if self._viewport else (),
            "wireframe": self._wire_btn.isChecked(),
            "grid": self._grid_visible,
            "am_mode": self._am_mode.value,
            "build_dir": self._build_dir,
            "boundary_conditions": self._boundary_conditions.copy(),
        }

        if self._actor is not None:
            snap["actor_props"] = _capture_actor_props(self._actor)

        return snap

    def _restore_snapshot(self, snap: dict) -> None:
        """
        Restore the viewer state from a history snapshot.
        """
        self._restoring = True
        try:
            target_file = snap.get("file")

            if target_file:
                target_file = os.path.abspath(target_file)
                if target_file != self._current_file or self._actor is None:
                    self.load_model(target_file, add_undo=False)
            else:
                self._clear_actor()

            if "background" in snap:
                self._viewport.set_background(*snap["background"])

            if self._actor is not None and "actor_props" in snap:
                _apply_actor_props(self._actor, snap["actor_props"])
                with _blocked(self._wire_btn):
                    self._wire_btn.setChecked(
                        snap["actor_props"].get("wireframe", False)
                    )

            self.show_grid(snap.get("grid", False))

            self._build_dir = snap.get("build_dir", (0.0, 0.0, 1.0))

            if "boundary_conditions" in snap:
                self._boundary_conditions = snap["boundary_conditions"]
                self._refresh_boundary_visualisation()
            else:
                self._boundary_conditions.clear()
                self._refresh_boundary_visualisation()

            am_mode_str = snap.get("am_mode", AnalysisMode.NONE.value)
            self._set_analysis_mode(AnalysisMode(am_mode_str))
        finally:
            self._restoring = False

        self._viewport.render()

    # ---------- Model loading ----------

    def load_model(self, path: str, *, add_undo: bool = True) -> bool:
        """
        Load a model file into the viewer.

        Parameters
        ----------
        path : str
            Path to the model file.  Supported formats: STL, OBJ, PLY, VTP,
            VTK, and EnSight Gold CASE.
        add_undo : bool, optional
            Whether to push the current state onto the undo stack before
            loading.

        Returns
        -------
        bool
            True if the model was loaded successfully, otherwise False.
        """
        path = os.path.abspath(path)

        if not os.path.isfile(path):
            logger.error("load_model: file not found: %s", path)
            self._set_status("File not found.")
            return False

        if add_undo:
            self._push_undo(f"Load {os.path.basename(path)}")

        self._cancel_wall_worker()
        self._clear_am_overlays()
        self._am_mode = AnalysisMode.NONE

        with _blocked(self._analysis_panel.modeRadioButtons[AnalysisMode.NONE]):
            self._analysis_panel.modeRadioButtons[AnalysisMode.NONE].setChecked(True)

        self._set_status(f"Loading {os.path.basename(path)} ...")
        ext = Path(path).suffix.lower()

        if ext == ".case":
            source_poly = self._load_case_polydata(path)
            if source_poly is None:
                return False
        else:
            reader = self._reader_for(path)
            try:
                reader.Update()
            except Exception:
                logger.exception("Reader failed for %s", path)
                self._set_status("Could not read file -- unsupported or corrupt.")
                return False

            tri = vtkTriangleFilter()
            tri.SetInputConnection(reader.GetOutputPort())
            tri.Update()
            source_poly = tri.GetOutput()

        self._source_poly = source_poly
        self._clear_analysis_cache()
        self._boundary_conditions.clear()
        if self._bc_mode_active:
            self._exit_bc_mode()

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(self._source_poly)

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(
            *vtkNamedColors().GetColor3d("LightSteelBlue")
        )
        actor.GetProperty().SetAmbient(0.2)
        actor.GetProperty().SetDiffuse(0.8)
        actor.GetProperty().SetSpecular(0.0)

        if self._actor is not None:
            self._viewport.remove_actor(self._actor)

        self._mapper = mapper
        self._plain_mapper = mapper
        self._actor = actor
        self._current_file = path

        self._viewport.add_actor(actor)
        self._viewport.update_grid(self._source_poly)

        with _blocked(self._wire_btn):
            self._wire_btn.setChecked(False)

        with _blocked(self._grid_btn):
            self._grid_btn.setChecked(self._grid_visible)

        if self._build_plate_actor:
            self._viewport.remove_actor(self._build_plate_actor)
            self._build_plate_actor = None
        if self._plate_action.isChecked():
            self.show_build_plate(True)

        self._analysis_panel.mesh_result_edit.setPlainText("-")
        self._analysis_panel.layer_info_label.setText("Layer: - / -")
        self._analysis_panel.layer_area_label.setText("Area: -")

        self._viewport.reset_camera()
        self._sync_undo_redo_ui()

        n_cells = self._num_cells()
        n_points = self._num_points()

        time_note = (
            f"  |  {len(self._case_time_steps)} time steps"
            if self._case_time_steps
            else ""
        )

        if self._is_huge_mesh():
            self._set_status(
                f"Loaded {os.path.basename(path)} "
                f"({n_points:,} pts, {n_cells:,} cells). "
                f"Large-mesh mode enabled.{time_note}"
            )
        else:
            self._set_status(
                f"Loaded {os.path.basename(path)} "
                f"({n_points:,} pts, {n_cells:,} cells).{time_note}"
            )

        self.model_loaded.emit(path)
        return True

    # ---------- Actor / scene helpers ----------

    def _clear_actor(self) -> None:
        """
        Remove the active model actor and clear model-related state.
        """
        self._case_reader = None
        self._case_time_steps = []

        if self._build_plate_actor:
            self._viewport.remove_actor(self._build_plate_actor)
            self._build_plate_actor = None

        if self._actor is not None:
            self._viewport.remove_actor(self._actor)
            self._actor = None
            self._mapper = None
            self._plain_mapper = None
            self._source_poly = None
            self._current_file = None
            self._clear_analysis_cache()
            self.show_grid(False)
            self._render()
            self._boundary_conditions.clear()
            if self._bc_mode_active:
                self._exit_bc_mode()

    def _set_analysis_mode(self, mode: AnalysisMode) -> None:
        """
        Switch the active additive-manufacturing analysis mode.
        """
        if self._bc_mode_active:
            self._exit_bc_mode()

        if self._actor is None and mode != AnalysisMode.NONE:
            self._set_status("Load a model first.")
            with _blocked(self._analysis_panel.modeRadioButtons[AnalysisMode.NONE]):
                self._analysis_panel.modeRadioButtons[
                    AnalysisMode.NONE
                ].setChecked(True)
            return

        if mode != AnalysisMode.WALL:
            self._cancel_wall_worker()

        self._clear_am_overlays()
        self._restore_plain_actor()
        self._am_mode = mode

        with _blocked(self._analysis_panel.modeRadioButtons[mode]):
            self._analysis_panel.modeRadioButtons[mode].setChecked(True)

        dispatch = {
            AnalysisMode.NONE: lambda: None,
            AnalysisMode.OVERHANG: self._run_overhang_analysis,
            AnalysisMode.WALL: self._start_wall_thickness,
            AnalysisMode.LAYER: self._setup_layer_preview,
            AnalysisMode.SUPPORT: self._run_support_estimate,
        }

        dispatch[mode]()
        self._render()

    # ---------- Cleanup ----------

    def cleanup(self) -> None:
        """
        Release workers, overlays, VTK resources, caches, and history state.
        """
        if getattr(self, "_cleaned_up", False):
            return

        self._cleaned_up = True
        logger.debug("ModelViewerWidget.cleanup() called")

        try:
            if hasattr(self, "_layer_update_timer"):
                self._layer_update_timer.stop()
                self._pending_layer_idx = None
        except Exception:
            logger.exception("cleanup: error stopping layer preview timer")

        try:
            self._cancel_wall_worker()
        except Exception:
            logger.exception("cleanup: error cancelling wall worker")

        try:
            self._clear_am_overlays()
        except Exception:
            logger.exception("cleanup: error clearing AM overlays")

        if self._build_plate_actor:
            self._viewport.remove_actor(self._build_plate_actor)
            self._build_plate_actor = None

        # FIX: explicitly release the VTK cell picker so its internal VTK
        # references (renderer, dataset) are freed before the viewport tears down.
        self._bc_picker = None

        if self._viewport:
            self._viewport.cleanup()

        self._actor = None
        self._mapper = None
        self._plain_mapper = None
        self._source_poly = None
        self._current_file = None
        self._viewport = None

        self._case_reader = None
        self._case_time_steps = []

        self._clear_analysis_cache()
        self._undo_manager.clear()
        self._sync_undo_redo_ui()

        logger.debug("ModelViewerWidget.cleanup() complete")

    # ---------- Status / render helpers ----------

    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)
        logger.debug("status: %s", message)

    def _render(self) -> None:
        if not self._restoring:
            self._viewport.render()

    def _num_cells(self) -> int:
        return self._source_poly.GetNumberOfCells() if self._source_poly else 0

    def _num_points(self) -> int:
        return self._source_poly.GetNumberOfPoints() if self._source_poly else 0

    def _is_large_mesh(self) -> bool:
        return self._num_cells() >= 500_000

    def _is_huge_mesh(self) -> bool:
        return self._num_cells() >= 1_000_000

    # ---------- Angle cache ----------

    def _clear_analysis_cache(self) -> None:
        self._angle_cache.clear()

    def _build_dir_cache_key(self) -> Tuple[float, float, float]:
        return tuple(round(float(v), 6) for v in self._build_dir)

    def _get_cell_angles_cached(
        self,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Return ``(angles, dots)`` for the current source poly and build direction.

        Both arrays are per-cell.

        * ``angles`` – float32, degrees in [0, 180].  0° = normal parallel to
          build dir; 90° = vertical face; >90° = overhanging.
        * ``dots`` – float64, clipped dot products n̂·d̂ in [−1, 1].  Negative
          values directly identify overhanging faces; ``−dots`` is a 0-to-1
          severity measure (0 = vertical, 1 = fully downward-facing).

        Results are cached by build direction (LRU, capped at
        ``_MAX_ANGLE_CACHE`` entries) to avoid redundant normal computation
        when the user re-selects a previously used direction.
        """
        if self._source_poly is None:
            empty = np.array([], dtype=np.float32)
            return empty, empty.astype(np.float64)

        key = self._build_dir_cache_key()

        if key in self._angle_cache:
            # Promote to most-recently-used position.
            self._angle_cache.move_to_end(key)
            return self._angle_cache[key]

        angles, _, dots = _compute_cell_angles(self._source_poly, self._build_dir)
        entry: Tuple[np.ndarray, np.ndarray] = (
            angles.astype(np.float32, copy=False),
            dots,
        )
        self._angle_cache[key] = entry
        self._angle_cache.move_to_end(key)

        # Evict the oldest entry if we have exceeded the cap.
        if len(self._angle_cache) > _MAX_ANGLE_CACHE:
            evicted_key, _ = self._angle_cache.popitem(last=False)
            logger.debug("Angle cache evicted key %s", evicted_key)

        return entry

    # ---------- Undo / redo ----------

    def _push_undo(self, action: str) -> None:
        self._undo_manager.push(self._snapshot(action))
        self._sync_undo_redo_ui()

    def _sync_undo_redo_ui(self) -> None:
        if not hasattr(self._toolbar, "undo_btn"):
            return
        self._toolbar.undo_btn.setEnabled(bool(self._undo_stack))
        self._toolbar.redo_btn.setEnabled(bool(self._redo_stack))

    def _apply_history(
        self,
        *,
        op: Callable[[dict], Optional[dict]],
        action: HistoryAction,
        empty_msg: str,
        verb: str,
    ) -> None:
        current = self._snapshot(action.value)
        snap = op(current)
        if snap is None:
            self._set_status(empty_msg)
            self._sync_undo_redo_ui()
            return
        self._restore_snapshot(snap)
        label = snap.get("action")
        if label and label not in ("undo", "redo"):
            self._set_status(f"{verb}: {label}")
        else:
            self._set_status(f"{verb}.")
        self._sync_undo_redo_ui()

    def undo(self) -> None:
        self._apply_history(
            op=self._undo_manager.undo,
            action=HistoryAction.UNDO,
            empty_msg="Nothing to undo.",
            verb="Undone",
        )

    def redo(self) -> None:
        self._apply_history(
            op=self._undo_manager.redo,
            action=HistoryAction.REDO,
            empty_msg="Nothing to redo.",
            verb="Redone",
        )

    # ---------- Drag-and-drop ----------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.load_model(path)
                break

    # ---------- File I/O ----------

    @classmethod
    def _reader_for(cls, path: str):
        ext = Path(path).suffix.lower()
        reader_cls = cls._READERS.get(ext, vtkXMLPolyDataReader)
        reader = reader_cls()
        reader.SetFileName(str(path))
        return reader

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open 3-D Model",
            os.getcwd(),
            "3-D Models (*.stl *.obj *.ply *.vtp *.vtk *.case);;All Files (*.*)",
        )
        if path:
            self.load_model(path)

    def _load_case_polydata(self, path: str) -> Optional[vtkPolyData]:
        # FIX: catch broad Exception so unexpected errors from CaseFileReader
        # (e.g. third-party library assertions) are handled gracefully rather
        # than propagating as an unhandled exception through load_model.
        try:
            reader = CaseFileReader(path)
            poly = reader.load(time_index=0)
        except Exception:
            logger.exception("CaseFileReader failed for %s", path)
            self._set_status(
                "Could not read .case file -- unsupported or corrupt."
            )
            return None
        tri = vtkTriangleFilter()
        tri.SetInputData(poly)
        tri.Update()
        self._case_reader = reader
        self._case_time_steps = reader.time_steps
        logger.debug(
            "CaseFileReader: %d block(s), %d time step(s), variables: %s",
            reader.n_blocks,
            len(self._case_time_steps),
            reader.variable_names,
        )
        return tri.GetOutput()

    def clear_model(self) -> None:
        self._cancel_wall_worker()
        self._clear_am_overlays()
        if self._actor is not None:
            self._clear_actor()
            self._set_status("Model cleared.")
            self.model_cleared.emit()

    def reset_camera(self) -> None:
        self._viewport.reset_camera()
        self._set_status("Camera reset.")

    # ---------- UI interactions ----------

    def _toggle_wireframe(self, checked: bool) -> None:
        if self._actor is None:
            with _blocked(self._wire_btn):
                self._wire_btn.setChecked(False)
            return
        if checked and self._is_huge_mesh():
            self._set_status(
                "Wireframe disabled for million-triangle meshes; "
                "use mesh check overlay or analysis coloring instead."
            )
            with _blocked(self._wire_btn):
                self._wire_btn.setChecked(False)
            return
        if checked:
            self._actor.GetProperty().SetRepresentationToWireframe()
            self._wire_btn.setIcon(
                QIcon(
                    colorize_pixmap(
                        QPixmap("line-icons:box-3-line.svg"),
                        self.palette().accent().color(),
                    )
                )
            )
        else:
            self._actor.GetProperty().SetRepresentationToSurface()
            self._wire_btn.setIcon(
                QIcon(
                    colorize_pixmap(
                        QPixmap("line-icons:global-line.svg"),
                        self.palette().accent().color(),
                    )
                )
            )
        self._render()

    def _choose_background(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if not color.isValid():
            return
        self._viewport.set_background(
            color.red() / 255.0,
            color.green() / 255.0,
            color.blue() / 255.0,
        )

    def _screenshot(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Screenshot",
            os.getcwd(),
            "PNG Image (*.png)",
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        w2if = vtkWindowToImageFilter()
        w2if.SetInput(self._vtk_widget.GetRenderWindow())
        w2if.Update()
        writer = vtkPNGWriter()
        writer.SetFileName(path)
        writer.SetInputConnection(w2if.GetOutputPort())
        writer.Write()
        self._set_status(f"Screenshot saved: {os.path.basename(path)}")

    def show_grid(self, visible: bool) -> None:
        self._grid_visible = visible
        self._viewport.show_grid(visible)
        with _blocked(self._grid_btn):
            self._grid_btn.setChecked(visible)

    def toggle_grid(self) -> None:
        self.show_grid(not self._grid_visible)

    def _show_export_dialog(self) -> None:
        if self._actor is None:
            self._set_status("No model loaded.")
            return
        path, sel = QFileDialog.getSaveFileName(
            self,
            "Export Model",
            os.getcwd(),
            "STL (*.stl);;OBJ (*.obj);;PLY (*.ply);;VTK (*.vtk)",
        )
        if not path:
            return
        if not Path(path).suffix:
            for token, ext in self._FILTER_EXT.items():
                if token in sel:
                    path += ext
                    break
        self._export_model(path)

    def _export_model(self, path: str) -> None:
        if self._source_poly is None:
            self._set_status("Nothing to export.")
            return
        ext = Path(path).suffix.lower()
        try:
            if ext == ".stl":
                writer = vtkSTLWriter()
                writer.SetFileName(path)
                writer.SetInputData(self._source_poly)
                writer.Write()
            elif ext == ".obj":
                prefix = str(Path(path).with_suffix(""))
                exporter = vtkOBJExporter()
                exporter.SetRenderWindow(self._vtk_widget.GetRenderWindow())
                exporter.SetFilePrefix(prefix)
                exporter.Write()
            elif ext == ".ply":
                writer = vtkPLYWriter()
                writer.SetFileName(path)
                writer.SetInputData(self._source_poly)
                writer.Write()
            else:
                writer = vtkPolyDataWriter()
                writer.SetFileName(path)
                writer.SetInputData(self._source_poly)
                writer.Write()
            self._set_status(f"Exported: {os.path.basename(path)}")
        except Exception:
            logger.exception("Export failed for %s", path)
            self._set_status("Export failed -- see log.")

    # ---------- Build direction ----------

    def _set_build_dir(self, vec: Tuple[float, float, float]) -> None:
        self._build_dir = vec
        self._refresh_analysis_if(self._am_mode)
        self._set_status(f"Build direction: {vec}")

    def _refresh_analysis_if(self, mode: AnalysisMode) -> None:
        if self._am_mode == mode:
            self._set_analysis_mode(mode)

    # ---------- AM overlay helpers ----------

    def _clear_am_overlays(self) -> None:
        if hasattr(self, "_layer_update_timer"):
            self._layer_update_timer.stop()
            self._pending_layer_idx = None
        for actor in self._am_overlays:
            self._viewport.remove_actor(actor)
        self._am_overlays.clear()
        if self._mesh_check_actor is not None:
            self._viewport.remove_actor(self._mesh_check_actor)
            self._mesh_check_actor = None
        self._hide_scalar_bar()

    def _restore_plain_actor(self) -> None:
        if self._actor is None:
            return
        if self._plain_mapper is not None:
            self._plain_mapper.ScalarVisibilityOff()
            self._actor.SetMapper(self._plain_mapper)
            self._mapper = self._plain_mapper
        prop = self._actor.GetProperty()
        prop.SetColor(*vtkNamedColors().GetColor3d("LightSteelBlue"))
        prop.SetOpacity(1.0)
        prop.SetAmbient(0.2)
        prop.SetDiffuse(0.8)
        prop.SetSpecular(0.0)
        if self._wire_btn.isChecked():
            prop.SetRepresentationToWireframe()
        else:
            prop.SetRepresentationToSurface()

    def _show_lighting_dialog(self) -> None:
        if self._actor is None:
            self._set_status("No model loaded.")
            return
        LightingDialog(
            self._actor,
            render_callback=self._viewport.render,
            parent=self,
        ).exec()

    def _show_statistics_dialog(self) -> None:
        StatisticsDialog(self._actor, parent=self).exec()

    def _show_scalar_bar(self, title: str, lut: vtkLookupTable) -> None:
        self._hide_scalar_bar()
        bar = vtkScalarBarActor()
        bar.SetLookupTable(lut)
        bar.SetTitle(title)
        bar.SetNumberOfLabels(5)
        bar.SetWidth(0.10)
        bar.SetHeight(0.40)
        bar.GetPositionCoordinate().SetCoordinateSystemToNormalizedDisplay()
        bar.GetPositionCoordinate().SetValue(0.88, 0.55)
        bar.GetTitleTextProperty().SetFontSize(10)
        bar.GetLabelTextProperty().SetFontSize(9)
        self._scalar_bar = bar
        self._viewport.add_actor2d(bar)

    def _hide_scalar_bar(self) -> None:
        if self._scalar_bar is not None:
            self._viewport.remove_actor2d(self._scalar_bar)
            self._scalar_bar = None

    # ---------- Mesh check ----------

    def _run_mesh_check(self) -> None:
        if self._source_poly is None:
            self._analysis_panel.mesh_result_edit.setPlainText(
                "No model loaded."
            )
            return
        pd = self._source_poly

        def _edge_filter(boundary: bool, non_manifold: bool) -> vtkFeatureEdges:
            feature_edges = vtkFeatureEdges()
            feature_edges.SetInputData(pd)
            feature_edges.SetBoundaryEdges(boundary)
            feature_edges.SetNonManifoldEdges(non_manifold)
            feature_edges.SetManifoldEdges(False)
            feature_edges.SetFeatureEdges(False)
            feature_edges.ColoringOff()
            feature_edges.Update()
            return feature_edges

        self._set_status("Running mesh integrity check...")
        fe_boundary = _edge_filter(True, False)
        fe_nm = _edge_filter(False, True)
        n_boundary = fe_boundary.GetOutput().GetNumberOfPoints()
        n_nm = fe_nm.GetOutput().GetNumberOfPoints()

        lines = [
            f"Points : {pd.GetNumberOfPoints()}",
            f"Cells  : {pd.GetNumberOfCells()}",
            "",
        ]
        issues = False
        lines.append(
            "PASS  No open boundaries"
            if n_boundary == 0
            else f"FAIL  Open boundaries: {n_boundary} pts"
        )
        if n_boundary > 0:
            issues = True
        lines.append(
            "PASS  No non-manifold edges"
            if n_nm == 0
            else f"FAIL  Non-manifold edges: {n_nm} pts"
        )
        if n_nm > 0:
            issues = True
        lines += [
            "",
            "Overall: PASS" if not issues else "Overall: ISSUES FOUND",
        ]
        self._analysis_panel.mesh_result_edit.setPlainText("\n".join(lines))

        if self._mesh_check_actor is not None:
            self._viewport.remove_actor(self._mesh_check_actor)
            self._mesh_check_actor = None
        if issues:
            append = vtkAppendPolyData()
            if n_boundary > 0:
                append.AddInputData(fe_boundary.GetOutput())
            if n_nm > 0:
                append.AddInputData(fe_nm.GetOutput())
            append.Update()
            bad_mapper = vtkPolyDataMapper()
            bad_mapper.SetInputData(append.GetOutput())
            bad_actor = vtkActor()
            bad_actor.SetMapper(bad_mapper)
            bad_actor.GetProperty().SetColor(1.0, 0.05, 0.05)
            bad_actor.GetProperty().SetLineWidth(3.0)
            bad_actor.GetProperty().SetRepresentationToWireframe()
            self._mesh_check_actor = bad_actor
            self._viewport.add_actor(bad_actor)
            self._render()
        n_issues = int(n_boundary > 0) + int(n_nm > 0)
        self._set_status(
            "Mesh check: PASS"
            if not issues
            else f"Mesh check: {n_issues} issue(s) found"
        )

    # ---------- Overhang analysis ----------

    def _run_overhang_analysis(self) -> None:
        if self._source_poly is None:
            return
        try:
            # FIX: unpack both arrays; use dots for the critical-cell count so
            # the sign of the dot product drives the mask rather than the 90°
            # proxy derived from arccos.
            angles, dots = self._get_cell_angles_cached()
        except RuntimeError as exc:
            self._set_status(str(exc))
            return

        overhang_offset_deg = self._analysis_panel.overhang_spin.value()
        threshold = 90.0 + overhang_offset_deg
        lut = _make_overhang_lut(threshold)

        pd = vtkPolyData()
        pd.ShallowCopy(self._source_poly)
        scalars = numpy_to_vtk(
            angles.astype(np.float32, copy=False),
            deep=True,
        )
        scalars.SetName("OverhangAngle")
        pd.GetCellData().SetScalars(scalars)

        am_mapper = vtkPolyDataMapper()
        am_mapper.SetInputData(pd)
        am_mapper.SetScalarModeToUseCellData()
        am_mapper.SetLookupTable(lut)
        am_mapper.SetScalarRange(0.0, 180.0)
        am_mapper.ScalarVisibilityOn()
        self._actor.SetMapper(am_mapper)
        self._mapper = am_mapper
        self._show_scalar_bar("Overhang (deg)", lut)
        self._render()

        # FIX: use the dot product directly.  A cell is critical when its
        # normal opposes the build direction by more than overhang_offset_deg
        # past vertical, i.e. dot < cos(threshold) = −sin(overhang_offset_deg).
        threshold_dot = -np.sin(np.radians(overhang_offset_deg))
        n_critical = int(np.sum(dots < threshold_dot))
        pct = 100.0 * n_critical / max(len(dots), 1)
        self._set_status(
            f"Overhang: {n_critical} critical cells ({pct:.1f}%) -- "
            f"threshold {overhang_offset_deg:.0f} deg from horizontal"
        )

    # ---------- Wall thickness ----------

    def _start_wall_thickness(self) -> None:
        if self._source_poly is None:
            return
        self._cancel_wall_worker()
        self._analysis_panel.wall_progress_label.setText(
            f"Computing on {self._num_points():,} points / "
            f"{self._num_cells():,} cells... 0%"
        )
        worker = WallThicknessWorker(self._source_poly)
        # FIX: use QueuedConnection so slots are always delivered on the main
        # thread via the event loop, regardless of how the worker emits signals.
        worker.progress.connect(
            lambda p: self._analysis_panel.wall_progress_label.setText(
                f"Computing... {p}%"
            ),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.result.connect(
            self._on_wall_thickness_result,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.error.connect(
            self._on_wall_thickness_error,
            Qt.ConnectionType.QueuedConnection,
        )
        self._wall_worker = worker
        worker.start()

    def _cancel_wall_worker(self) -> None:
        if self._wall_worker is not None and self._wall_worker.isRunning():
            self._wall_worker.cancel()
            # FIX: apply a timeout so a stalled worker cannot block the main
            # thread (e.g. during application shutdown) indefinitely.
            finished = self._wall_worker.wait(_WORKER_STOP_TIMEOUT_MS)
            if not finished:
                logger.warning(
                    "_cancel_wall_worker: worker did not stop within %d ms",
                    _WORKER_STOP_TIMEOUT_MS,
                )
        self._wall_worker = None
        if hasattr(self, "_analysis_panel"):
            self._analysis_panel.wall_progress_label.setText("")

    def _on_wall_thickness_result(self, thicknesses: np.ndarray) -> None:
        self._analysis_panel.wall_progress_label.setText("")
        if self._am_mode != AnalysisMode.WALL or self._actor is None:
            return
        pd = vtkPolyData()
        pd.ShallowCopy(self._source_poly)
        valid = thicknesses[thicknesses < thicknesses.max()]
        min_t = float(valid.min()) if len(valid) else 0.0
        max_t = float(np.percentile(thicknesses, 95))
        scalars = numpy_to_vtk(
            np.clip(thicknesses, min_t, max_t).astype(np.float32),
            deep=True,
        )
        scalars.SetName("WallThickness")
        pd.GetPointData().SetScalars(scalars)
        lut = _make_wall_lut(min_t, max_t)
        am_mapper = vtkPolyDataMapper()
        am_mapper.SetInputData(pd)
        am_mapper.SetScalarModeToUsePointData()
        am_mapper.SetLookupTable(lut)
        am_mapper.SetScalarRange(min_t, max_t)
        am_mapper.ScalarVisibilityOn()
        self._actor.SetMapper(am_mapper)
        self._mapper = am_mapper
        self._show_scalar_bar("Thickness (mm)", lut)
        self._render()
        min_wall = self._analysis_panel.min_wall_spin.value()
        n_thin = int(np.sum(thicknesses < min_wall))
        pct = 100 * n_thin / max(len(thicknesses), 1)
        self._set_status(
            f"Wall thickness: {n_thin} thin points ({pct:.1f}%) "
            f"below {min_wall:.2f} mm target  |  "
            f"range {min_t:.2f}-{max_t:.2f} mm"
        )

    def _on_wall_thickness_error(self, msg: str) -> None:
        self._analysis_panel.wall_progress_label.setText("")
        self._set_status(f"Wall thickness error: {msg}")

    # ---------- Layer preview ----------

    def _setup_layer_preview(self) -> None:
        if self._source_poly is None:
            return
        self._actor.GetProperty().SetOpacity(0.22)
        self._rebuild_layer_slider()
        self._update_layer_preview(self._analysis_panel.layer_slider.value())

    def _rebuild_layer_slider(self) -> None:
        if self._source_poly is None:
            return
        _, height = _model_base_and_height(
            self._source_poly.GetBounds(),
            self._build_dir,
        )
        thickness = self._analysis_panel.layer_thickness_spin.value() / 1000.0
        n_layers = max(1, int(math.ceil(height / thickness)))
        prev = self._analysis_panel.layer_slider.value()
        self._analysis_panel.layer_slider.setRange(0, n_layers - 1)
        self._analysis_panel.layer_slider.setValue(min(prev, n_layers - 1))

    def _update_layer_preview(self, layer_idx: int) -> None:
        if self._am_mode != AnalysisMode.LAYER or self._source_poly is None:
            return
        self._pending_layer_idx = int(layer_idx)
        delay_ms = 140 if self._is_large_mesh() else 40
        self._layer_update_timer.start(delay_ms)

    def _perform_layer_preview_update(self) -> None:
        if self._pending_layer_idx is None:
            return
        layer_idx = self._pending_layer_idx
        self._pending_layer_idx = None
        if self._am_mode != AnalysisMode.LAYER or self._source_poly is None:
            return
        for actor in self._am_overlays:
            self._viewport.remove_actor(actor)
        self._am_overlays.clear()

        thickness = self._analysis_panel.layer_thickness_spin.value() / 1000.0
        build = np.array(self._build_dir, dtype=float)
        norm = np.linalg.norm(build)
        if norm == 0.0:
            self._set_status("Layer preview error: build direction is zero.")
            return
        build /= norm

        base_h, _ = _model_base_and_height(
            self._source_poly.GetBounds(),
            self._build_dir,
        )
        layer_h = base_h + (layer_idx + 1) * thickness

        # build * layer_h is a point P where P · build_hat == layer_h (since
        # build_hat is unit length), which is a valid origin for the cut plane
        # regardless of where the model sits in world space.
        origin = (build * layer_h).tolist()

        n_layers = self._analysis_panel.layer_slider.maximum() + 1
        plane = vtkPlane()
        plane.SetNormal(*build)
        plane.SetOrigin(*origin)
        cutter = vtkCutter()
        cutter.SetInputData(self._source_poly)
        cutter.SetCutFunction(plane)
        cutter.Update()
        triangulator = vtkContourTriangulator()
        triangulator.SetInputConnection(cutter.GetOutputPort())
        triangulator.Update()
        filled_pd = triangulator.GetOutput()

        section_mapper = vtkPolyDataMapper()
        section_mapper.SetInputData(filled_pd)
        section_mapper.ScalarVisibilityOff()
        section_actor = vtkActor()
        section_actor.SetMapper(section_mapper)
        section_actor.GetProperty().SetColor(1.0, 0.55, 0.0)
        section_actor.GetProperty().SetOpacity(0.95)
        section_actor.GetProperty().SetAmbient(0.4)
        section_actor.GetProperty().SetDiffuse(0.6)
        self._am_overlays.append(section_actor)
        self._viewport.add_actor(section_actor)

        area = 0.0
        try:
            for i in range(filled_pd.GetNumberOfCells()):
                cell = filled_pd.GetCell(i)
                if cell.GetNumberOfPoints() == 3:
                    p0 = np.array(filled_pd.GetPoint(cell.GetPointId(0)))
                    p1 = np.array(filled_pd.GetPoint(cell.GetPointId(1)))
                    p2 = np.array(filled_pd.GetPoint(cell.GetPointId(2)))
                    area += 0.5 * float(
                        np.linalg.norm(np.cross(p1 - p0, p2 - p0))
                    )
        except Exception:
            logger.warning("Layer preview: could not compute cross-section area")

        self._analysis_panel.layer_info_label.setText(
            f"Layer: {layer_idx + 1} / {n_layers}"
        )
        self._analysis_panel.layer_area_label.setText(
            f"Area: {area:.2f} mm\u00B2"
        )
        self._render()
        self._set_status(
            f"Layer {layer_idx + 1}/{n_layers}  "
            f"h={layer_h:.3f} mm  area={area:.2f} mm\u00B2"
        )

    # ---------- Support estimate ----------

    def _run_support_estimate(self) -> None:
        if self._source_poly is None:
            return
        try:
            # FIX: unpack both arrays; use dots for the overhang mask so the
            # sign of the dot product is authoritative rather than the 90°
            # arccos proxy.
            angles, dots = self._get_cell_angles_cached()
        except RuntimeError as exc:
            self._set_status(str(exc))
            return

        overhang_offset_deg = self._analysis_panel.overhang_spin.value()
        # dot < −sin(offset) ↔ angle > 90° + offset
        threshold_dot = -np.sin(np.radians(overhang_offset_deg))
        overhang_mask = dots < threshold_dot

        if not np.any(overhang_mask):
            self._set_status("Support: no overhanging faces detected.")
            return

        self._actor.GetProperty().SetOpacity(0.28)
        self._actor.GetProperty().SetColor(*vtkNamedColors().GetColor3d("Silver"))

        overhang_pd = _extract_cells_by_mask(self._source_poly, overhang_mask)
        oh_mapper = vtkPolyDataMapper()
        oh_mapper.SetInputData(overhang_pd)
        oh_mapper.ScalarVisibilityOff()
        oh_actor = vtkActor()
        oh_actor.SetMapper(oh_mapper)
        oh_actor.GetProperty().SetColor(0.95, 0.10, 0.05)
        oh_actor.GetProperty().SetOpacity(0.90)
        oh_actor.GetProperty().SetAmbient(0.3)
        oh_actor.GetProperty().SetDiffuse(0.7)
        self._am_overlays.append(oh_actor)
        self._viewport.add_actor(oh_actor)

        try:
            total_area, total_vol = self._estimate_support_volume_vectorized(
                overhang_mask
            )
        except Exception:
            logger.exception("Vectorized support estimate failed")
            self._set_status("Support estimate failed -- see log.")
            self._render()
            return

        self._render()
        self._set_status(
            f"Support: {int(np.sum(overhang_mask))} overhanging cells  |  "
            f"projected area {total_area:.1f} mm\u00B2  |  "
            f"estimated support vol ~{total_vol:.1f} mm\u00B3"
        )

    def _triangle_indices_from_polydata(self, pd: vtkPolyData) -> np.ndarray:
        polys_vtk = pd.GetPolys()
        if polys_vtk is None:
            return np.empty((0, 3), dtype=np.int64)
        legacy = vtk_to_numpy(polys_vtk.GetData())
        if legacy.size:
            n_cells = pd.GetNumberOfCells()
            if legacy.size % 4 == 0:
                cells = legacy.reshape(-1, 4)
                if cells.shape[0] == n_cells and np.all(cells[:, 0] == 3):
                    return cells[:, 1:4].astype(np.int64, copy=False)
        if (
            hasattr(polys_vtk, "GetConnectivityArray")
            and hasattr(polys_vtk, "GetOffsetsArray")
        ):
            connectivity_array = polys_vtk.GetConnectivityArray()
            offsets_array = polys_vtk.GetOffsetsArray()
            if connectivity_array is not None and offsets_array is not None:
                connectivity = vtk_to_numpy(connectivity_array)
                offsets = vtk_to_numpy(offsets_array)
                if offsets.size >= 2:
                    lengths = np.diff(offsets)
                    if not np.all(lengths == 3):
                        raise RuntimeError(
                            "Expected only triangle cells in support estimate."
                        )
                    starts = offsets[:-1].astype(np.int64, copy=False)
                    tri_ids = connectivity[
                        starts[:, None] + np.arange(3, dtype=np.int64)
                    ]
                    return tri_ids.astype(np.int64, copy=False)
        raise RuntimeError(
            "Expected triangulated VTK cell array with triangle connectivity."
        )

    def _estimate_support_volume_vectorized(
        self,
        overhang_mask: np.ndarray,
    ) -> Tuple[float, float]:
        pd = self._source_poly
        if pd is None:
            return 0.0, 0.0
        points_vtk = pd.GetPoints()
        if points_vtk is None:
            return 0.0, 0.0
        points = vtk_to_numpy(points_vtk.GetData())
        tri_ids = self._triangle_indices_from_polydata(pd)
        if tri_ids.size == 0:
            return 0.0, 0.0
        if len(overhang_mask) != tri_ids.shape[0]:
            raise RuntimeError(
                "Overhang mask length does not match triangle count."
            )
        tri_ids_oh = tri_ids[overhang_mask]
        if tri_ids_oh.size == 0:
            return 0.0, 0.0
        tri_pts = points[tri_ids_oh]
        p0 = tri_pts[:, 0, :]
        p1 = tri_pts[:, 1, :]
        p2 = tri_pts[:, 2, :]
        cross = np.cross(p1 - p0, p2 - p0)
        areas = 0.5 * np.linalg.norm(cross, axis=1)
        centroids = tri_pts.mean(axis=1)
        base_h, _ = _model_base_and_height(
            pd.GetBounds(),
            self._build_dir,
        )
        build = np.array(self._build_dir, dtype=np.float64)
        norm = np.linalg.norm(build)
        if norm == 0.0:
            raise RuntimeError("Build direction vector has zero length.")
        build /= norm
        heights = np.maximum(0.0, centroids @ build - base_h)
        total_area = float(np.sum(areas))
        total_vol = float(np.sum(areas * heights))
        return total_area, total_vol

    def closeEvent(self, event) -> None:
        self.cleanup()
        event.accept()