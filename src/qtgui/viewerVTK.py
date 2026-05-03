"""
Embeddable 3D Model Viewer Widget for PyQt6 — Additive Manufacturing edition.

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

AM features (in the side panel)
--------------------------------
1. Mesh Integrity Check
2. Overhang Heat Map
3. Layer Preview
4. Support Volume Estimate
5. Wall Thickness Map

Supported file formats
----------------------
Read  : STL, OBJ, PLY, VTP, VTK (legacy poly-data)
Write : STL, OBJ, PLY, VTK

Minimal embedding example::

    from model_viewer_widget import configure_surface_format, ModelViewerWidget

    configure_surface_format()
    app = QApplication(sys.argv)
    viewer = ModelViewerWidget()
    viewer.show()
    sys.exit(app.exec())
"""

__all__ = ["configure_surface_format", "ModelViewerWidget"]

import itertools
import logging
import math
import os
import threading
from collections import deque
from enum import StrEnum, unique
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import vtkmodules.all as vtk
import vtkmodules.vtkInteractionStyle
import vtkmodules.vtkRenderingOpenGL2
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QSurfaceFormat, QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QToolButton,
)
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkIdList, vtkPoints, vtkLookupTable
from vtkmodules.vtkCommonDataModel import vtkPlane, vtkPolyData
from vtkmodules.vtkFiltersCore import (
    vtkAppendPolyData,
    vtkCutter,
    vtkFeatureEdges,
    vtkPolyDataNormals,
    vtkTriangleFilter,
)
from vtkmodules.vtkFiltersGeneral import vtkContourTriangulator, vtkOBBTree
from vtkmodules.vtkIOExport import vtkOBJExporter
from vtkmodules.vtkIOGeometry import vtkOBJReader, vtkSTLReader, vtkSTLWriter
from vtkmodules.vtkIOImage import vtkPNGWriter
from vtkmodules.vtkIOLegacy import vtkPolyDataReader, vtkPolyDataWriter
from vtkmodules.vtkIOPLY import vtkPLYReader, vtkPLYWriter
from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import (
    vtkAxesActor,
    vtkCubeAxesActor,
    vtkScalarBarActor,
)
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkRenderer,
    vtkWindowToImageFilter,
)

from pycore.platform import IS_MACOS
from qtcore.vtk_utils import SafeVTKWidget
from qtgui.style.toolbar import StyledToolBar

logger = logging.getLogger(__name__)

_NAMED_COLORS = vtkNamedColors()


@unique
class AnalysisMode(StrEnum):
    """Enumeration of available AM analysis modes."""
    NONE = "none"
    OVERHANG = "overhang"
    WALL = "wall"
    LAYER = "layer"
    SUPPORT = "support"


def configure_surface_format():
    """Configure the default OpenGL surface format for the application.

    Must be called **once** before creating a ``QApplication`` instance.

    Notes
    -----
    This function sets the default surface format to use OpenGL 4.1 core
    profile, which is required for the VTK rendering context.
    """
    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setVersion(4, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)



def _capture_actor_props(actor: vtkActor) -> dict:
    """Return a serialisable snapshot of the actor's visual properties.

    Parameters
    ----------
    actor : vtkActor
        The actor whose properties to capture.

    Returns
    -------
    dict
        A dictionary with keys ``ambient``, ``diffuse``, ``specular``,
        ``color`` (tuple of RGB), ``opacity``, and ``wireframe``.
    """
    prop = actor.GetProperty()
    return {
        "ambient": prop.GetAmbient(),
        "diffuse": prop.GetDiffuse(),
        "specular": prop.GetSpecular(),
        "color": tuple(prop.GetColor()),
        "opacity": prop.GetOpacity(),
        "wireframe": prop.GetRepresentation() == vtk.VTK_WIREFRAME,
    }


def _apply_actor_props(actor: vtkActor, props: dict) -> None:
    """Restore visual properties captured by _capture_actor_props.

    Parameters
    ----------
    actor : vtkActor
        The actor to which properties will be applied.
    props : dict
        A dictionary containing the property values as generated by
        ``_capture_actor_props``.
    """
    prop = actor.GetProperty()
    prop.SetAmbient(props["ambient"])
    prop.SetDiffuse(props["diffuse"])
    prop.SetSpecular(props["specular"])
    prop.SetColor(*props["color"])
    prop.SetOpacity(props.get("opacity", 1.0))
    if props["wireframe"]:
        prop.SetRepresentationToWireframe()
    else:
        prop.SetRepresentationToSurface()


def _make_overhang_lut(threshold_deg: float) -> vtkLookupTable:
    """Return a lookup table for overhang angles (0-180°).

    Parameters
    ----------
    threshold_deg : float
        The overhang threshold in degrees above horizontal (i.e., 90° + offset).
        Angles above this value are considered critical (red).

    Returns
    -------
    vtkLookupTable
        A lookup table that maps angles to colours:
        - green for 0–90° (safe),
        - gradient from orange to red for 90°–`threshold_deg`,
        - red for >`threshold_deg`.
    """
    lut = vtkLookupTable()
    lut.SetNumberOfTableValues(256)
    lut.SetRange(0.0, 180.0)
    for i in range(256):
        angle = (i / 255.0) * 180.0
        if angle <= 90.0:
            lut.SetTableValue(i, 0.15, 0.78, 0.15, 1.0)
        elif angle <= threshold_deg:
            t = (angle - 90.0) / max(threshold_deg - 90.0, 1e-6)
            lut.SetTableValue(i, 1.0, 0.65 * (1 - t) + 0.25 * t, 0.0, 1.0)
        else:
            lut.SetTableValue(i, 0.90, 0.12, 0.05, 1.0)
    lut.Build()
    return lut


def _make_wall_lut(min_mm: float, max_mm: float) -> vtkLookupTable:
    """Return a lookup table for wall thickness (red=thin, green=thick).

    Parameters
    ----------
    min_mm : float
        Minimum wall thickness value (mapped to red).
    max_mm : float
        Maximum wall thickness value (mapped to green).

    Returns
    -------
    vtkLookupTable
        A lookup table with a red-to-green gradient over the range
        [`min_mm`, `max_mm`].
    """
    lut = vtkLookupTable()
    lut.SetNumberOfTableValues(256)
    lut.SetRange(min_mm, max_mm)
    for i in range(256):
        t = i / 255.0
        lut.SetTableValue(i, 1.0 - t, t * 0.78, 0.05, 1.0)
    lut.Build()
    return lut


def _extract_cells_by_mask(poly_data: vtkPolyData,
                           mask: np.ndarray) -> vtkPolyData:
    """Return a new vtkPolyData containing only cells where mask is True.

    Parameters
    ----------
    poly_data : vtkPolyData
        The input polydata.
    mask : np.ndarray of bool
        A boolean array with True for cells to keep.

    Returns
    -------
    vtkPolyData
        A new polydata with the same points but only the selected cells.
    """
    new_pd = vtkPolyData()
    new_pts = vtkPoints()
    new_pts.DeepCopy(poly_data.GetPoints())
    new_pd.SetPoints(new_pts)
    new_pd.Allocate()
    for cell_id in np.where(mask)[0]:
        cell = poly_data.GetCell(int(cell_id))
        new_pd.InsertNextCell(cell.GetCellType(), cell.GetPointIds())
    new_pd.BuildLinks()
    return new_pd


def _model_base_and_height(
        bounds: tuple, build_dir: Tuple[float, float, float]
) -> Tuple[float, float]:
    """Return (base_h, height) for bounds projected along build_dir.

    Parameters
    ----------
    bounds : tuple of float
        Six-element bounds (xmin, xmax, ymin, ymax, zmin, zmax).
    build_dir : tuple of float
        Unit build direction vector.

    Returns
    -------
    (float, float)
        base_h : the minimal projection of the model corners onto the build direction.
        height : the difference between maximal and minimal projections.
    """
    b = bounds
    direction = np.asarray(build_dir, dtype=np.float64)
    direction = direction / np.linalg.norm(direction)
    corners = np.array(
        list(itertools.product([b[0], b[1]], [b[2], b[3]], [b[4], b[5]]))
    )
    projections = corners @ direction
    return float(projections.min()), float(
        projections.max() - projections.min())


def _compute_cell_angles(poly_data: vtkPolyData,
                         build_dir: Tuple[float, float, float]
                         ) -> Tuple[np.ndarray, np.ndarray]:
    """Compute angle (deg) between each cell normal and the build direction.

    Parameters
    ----------
    poly_data : vtkPolyData
        The input surface mesh.
    build_dir : tuple of float
        Unit build direction vector.

    Returns
    -------
    angles : ndarray of float32
        Array of angles in degrees.
    cell_normals : ndarray of float64
        Array of normal vectors for each cell.
    """
    nf = vtkPolyDataNormals()
    nf.SetInputData(poly_data)
    nf.ComputeCellNormalsOn()
    nf.ComputePointNormalsOff()
    nf.SplittingOff()
    nf.ConsistencyOn()
    nf.Update()
    output = nf.GetOutput()
    normals_vtk = output.GetCellData().GetNormals()
    if normals_vtk is None:
        raise RuntimeError("Could not compute cell normals.")
    cell_normals = vtk_to_numpy(normals_vtk)
    build = np.array(build_dir, dtype=np.float64)
    build /= np.linalg.norm(build)
    dots = np.clip(cell_normals @ build, -1.0, 1.0)
    angles = np.degrees(np.arccos(dots)).astype(np.float32)
    return angles, cell_normals


class _WallThicknessWorker(QThread):
    """Compute per-point wall thickness via inward ray casting."""

    progress = pyqtSignal(int)  # 0-100
    result = pyqtSignal(object)  # np.ndarray[float32]
    error = pyqtSignal(str)

    _SAMPLE_TARGET: int = 8_000

    def __init__(self, poly_data: vtkPolyData) -> None:
        """Initialise the worker with a deep copy of the input polydata.

        Parameters
        ----------
        poly_data : vtkPolyData
            The mesh on which to compute wall thickness.
        """
        super().__init__()
        safe_copy = vtkPolyData()
        safe_copy.DeepCopy(poly_data)
        self._poly_data = safe_copy
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation of the running computation."""
        self._cancel_event.set()

    def run(self) -> None:
        """Thread entry point; calls ``_compute`` with error handling."""
        try:
            self._compute()
        except Exception:
            logger.exception("WallThicknessWorker failed")
            self.error.emit("Wall thickness computation failed -- see log.")

    def _compute(self) -> None:
        """Perform the ray-casting thickness computation."""
        pd = self._poly_data

        tri = vtkTriangleFilter()
        tri.SetInputData(pd)
        tri.Update()

        nf = vtkPolyDataNormals()
        nf.SetInputConnection(tri.GetOutputPort())
        nf.ComputePointNormalsOn()
        nf.ComputeCellNormalsOff()
        nf.SplittingOff()
        nf.ConsistencyOn()
        nf.Update()
        tri_pd = nf.GetOutput()

        points = vtk_to_numpy(tri_pd.GetPoints().GetData())
        normals = vtk_to_numpy(tri_pd.GetPointData().GetNormals())
        n_pts = len(points)

        b = tri_pd.GetBounds()
        max_len = math.sqrt(
            (b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2 + (b[5] - b[4]) ** 2
        )

        thicknesses = np.full(n_pts, max_len, dtype=np.float32)

        obb = vtkOBBTree()
        obb.SetDataSet(tri_pd)
        obb.SetMaxLevel(12)
        obb.BuildLocator()

        step = max(1, n_pts // self._SAMPLE_TARGET)
        indices = list(range(0, n_pts, step))
        total_work = len(indices)
        pts_vtk = vtkPoints()
        cells_vtk = vtkIdList()

        for work_idx, pt_idx in enumerate(indices):
            if self._cancel_event.is_set():
                return

            p = points[pt_idx]
            n = normals[pt_idx]

            p1 = (p + 1e-4 * n).tolist()
            p2 = (p - max_len * n).tolist()

            pts_vtk.Reset()
            cells_vtk.Reset()
            code = obb.IntersectWithLine(p1, p2, pts_vtk, cells_vtk)

            if code != 0 and pts_vtk.GetNumberOfPoints() > 0:
                ip = np.array(pts_vtk.GetPoint(0))
                thicknesses[pt_idx] = float(np.linalg.norm(ip - p))

            if work_idx % max(1, total_work // 20) == 0:
                self.progress.emit(int(100 * work_idx / total_work))

        self.progress.emit(100)
        self.result.emit(thicknesses)


class LightingDialog(QDialog):
    """Non‑blocking dialog for live adjustment of actor lighting properties."""

    def __init__(self, actor: vtkActor, render_window, parent=None) -> None:
        """Initialise the dialog with the target actor and render window.

        Parameters
        ----------
        actor : vtkActor
            The actor whose lighting properties can be adjusted.
        render_window : vtkRenderWindow
            The render window to refresh after changes.
        parent : QWidget, optional
            Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Lighting Controls")
        self.setFixedSize(320, 185)
        self._actor = actor
        self._rw = render_window

        layout = QGridLayout(self)
        specs = [
            ("Ambient", "ambient", actor.GetProperty().GetAmbient()),
            ("Diffuse", "diffuse", actor.GetProperty().GetDiffuse()),
            ("Specular", "specular", actor.GetProperty().GetSpecular()),
        ]
        self._spinboxes: Dict[str, QDoubleSpinBox] = {}
        for row, (label, key, current) in enumerate(specs):
            layout.addWidget(QLabel(f"{label}:"), row, 0)
            sb = QDoubleSpinBox()
            sb.setRange(0.0, 1.0)
            sb.setSingleStep(0.05)
            sb.setDecimals(2)
            sb.setValue(current)
            sb.valueChanged.connect(self._apply)
            layout.addWidget(sb, row, 1)
            self._spinboxes[key] = sb

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons, len(specs), 0, 1, 2)

    def _apply(self) -> None:
        """Transfer spinbox values to the actor and re-render."""
        prop = self._actor.GetProperty()
        prop.SetAmbient(self._spinboxes["ambient"].value())
        prop.SetDiffuse(self._spinboxes["diffuse"].value())
        prop.SetSpecular(self._spinboxes["specular"].value())
        self._rw.Render()


class StatisticsDialog(QDialog):
    """Read-only dialog displaying geometry and material statistics."""

    def __init__(self, actor, parent=None) -> None:
        """Initialise the statistics dialog.

        Parameters
        ----------
        actor : vtkActor or None
            The actor for which statistics are displayed, or None if no model loaded.
        parent : QWidget, optional
            Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Model Statistics")
        self.setMinimumSize(420, 360)

        layout = QVBoxLayout(self)
        text_area = QTextEdit(readOnly=True)
        text_area.setText(self._build_report(actor))
        layout.addWidget(text_area)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    @staticmethod
    def _build_report(actor: Optional[vtkActor]) -> str:
        """Generate a textual report from an actor.

        Parameters
        ----------
        actor : vtkActor or None
            The actor to inspect.

        Returns
        -------
        str
            Formatted report string.
        """
        if actor is None:
            return "No model loaded."

        lines = ["=== Model Statistics ===", ""]

        try:
            b = actor.GetBounds()
            lines += [
                "Bounds:",
                f"  X : {b[0]:.4f}  to  {b[1]:.4f}",
                f"  Y : {b[2]:.4f}  to  {b[3]:.4f}",
                f"  Z : {b[4]:.4f}  to  {b[5]:.4f}",
                "",
                "Dimensions:",
                f"  X : {b[1] - b[0]:.4f}",
                f"  Y : {b[3] - b[2]:.4f}",
                f"  Z : {b[5] - b[4]:.4f}",
                "",
            ]
        except Exception as exc:
            lines += [f"[Bounds unavailable: {exc}]", ""]

        mapper = actor.GetMapper()
        if mapper is not None:
            try:
                data = mapper.GetInput()
                if data is None:
                    raise RuntimeError("mapper.GetInput() returned None")
                lines += [
                    "Geometry:",
                    f"  Points   : {data.GetNumberOfPoints()}",
                    f"  Polygons : {data.GetNumberOfCells()}",
                    "",
                ]
            except Exception as exc:
                logger.warning("Statistics: could not read geometry -- %s", exc)
                lines += [f"[Geometry unavailable: {exc}]", ""]

        try:
            prop = actor.GetProperty()
            lines += [
                "Material:",
                f"  Ambient  : {prop.GetAmbient():.2f}",
                f"  Diffuse  : {prop.GetDiffuse():.2f}",
                f"  Specular : {prop.GetSpecular():.2f}",
            ]
        except Exception as exc:
            logger.warning("Statistics: could not read material -- %s", exc)
            lines.append(f"[Material unavailable: {exc}]")

        return "\n".join(lines)


class ModelViewerWidget(QWidget):
    """Embeddable PyQt6 widget for interactive 3‑D model viewing.

    Signals
    -------
    model_loaded(str)
        Emitted with the absolute file path after a model loads successfully.
    model_cleared()
        Emitted when the scene is cleared.
    """

    model_loaded = pyqtSignal(str)
    model_cleared = pyqtSignal()

    _MAX_HISTORY: int = 20

    def __init__(self, parent=None) -> None:
        """Construct the viewer widget.

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

        self._undo_stack: deque = deque(maxlen=self._MAX_HISTORY)
        self._redo_stack: deque = deque(maxlen=self._MAX_HISTORY)

        self._am_mode: AnalysisMode = AnalysisMode.NONE
        self._build_dir: Tuple[float, float, float] = (0.0, 0.0, 1.0)
        self._am_overlays: list = []
        self._scalar_bar: Optional[vtkScalarBarActor] = None
        self._mesh_check_actor: Optional[vtkActor] = None
        self._wall_worker: Optional[_WallThicknessWorker] = None

        self._grid_visible: bool = False
        self._cube_axes: Optional[vtkCubeAxesActor] = None

        self._setup_ui()
        QTimer.singleShot(500, self._init_vtk)

    def _setup_ui(self) -> None:
        """Build the full user interface: toolbar, VTK viewport, and AM panel."""
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(2)

        toolbar = StyledToolBar("Main Toolbar")
        root.addWidget(toolbar)

        def _btn(label: str, slot, icon: Optional[str] = None) -> QToolButton:
            b = QToolButton()
            b.setToolTip(label)
            if icon:
                b.setIcon(QIcon(icon))
            b.clicked.connect(slot)
            toolbar.addWidget(b)
            return b

        _btn("Open", self.open_file, icon="line-icons:file-add-line.svg")
        _btn("Export", self._show_export_dialog,
             icon="line-icons:export-line.svg")
        toolbar.addSeparator()
        _btn("Reset Camera", self.reset_camera,
             icon="line-icons:camera-switch-line.svg")

        self._wire_btn = QToolButton()
        self._wire_btn.setCheckable(True)
        self._wire_btn.setIcon(QIcon("line-icons:global-line.svg"))
        self._wire_btn.setToolTip("Toggle wireframe/solid")
        self._wire_btn.toggled.connect(self._toggle_wireframe)
        toolbar.addWidget(self._wire_btn)

        self._grid_btn = QToolButton()
        self._grid_btn.setCheckable(True)
        self._grid_btn.setIcon(QIcon("line-icons:grid-line.svg"))
        self._grid_btn.setToolTip("Toggle bounding-box grid")
        self._grid_btn.toggled.connect(self.toggle_grid)
        toolbar.addWidget(self._grid_btn)

        _btn("Background", self._choose_background,
             icon="line-icons:multi-image-line.svg")
        toolbar.addSeparator()
        _btn("Lighting", self._show_lighting_dialog,
             icon="line-icons:lightbulb-line.svg")
        _btn("Statistics", self._show_statistics_dialog,
             icon="line-icons:donut-chart-line.svg")
        _btn("Screenshot", self._screenshot,
             icon="line-icons:camera-lens-line.svg")
        toolbar.addSeparator()
        _btn("Undo", self.undo,
             icon="line-icons:arrow-go-back-line.svg")
        _btn("Redo", self.redo,
             icon="line-icons:arrow-go-forward-line.svg")
        toolbar.addSeparator()

        self._status_label = QLabel("Ready")
        toolbar.addWidget(self._status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        self._vtk_widget = SafeVTKWidget(self)
        splitter.addWidget(self._vtk_widget)

        am_panel = self._build_am_panel()
        splitter.addWidget(am_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, 240])

        self._renderer = vtkRenderer()
        self._vtk_widget.GetRenderWindow().AddRenderer(self._renderer)

        style = vtkInteractorStyleTrackballCamera()
        self._vtk_widget._Iren.SetInteractorStyle(style)

        colors = vtkNamedColors()
        self._renderer.SetBackground(colors.GetColor3d("SlateGray"))

        axes = vtkAxesActor()
        self._ori_marker = vtkOrientationMarkerWidget()
        self._ori_marker.SetInteractor(self._vtk_widget._Iren)
        self._ori_marker.SetOrientationMarker(axes)
        self._ori_marker.SetEnabled(1)
        self._ori_marker.InteractiveOn()

        self.setAcceptDrops(True)

    def _build_am_panel(self) -> QWidget:
        """Construct the right-hand analysis panel with all controls.

        Returns
        -------
        QWidget
            The configured panel widget.
        """
        panel = QWidget()
        panel.setFixedWidth(240)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        mode_group = QGroupBox("Analysis Mode")
        mode_layout = QVBoxLayout(mode_group)
        self._mode_btn_group = QButtonGroup(self)
        self._mode_radio: Dict[AnalysisMode, QRadioButton] = {}
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
            rb.clicked.connect(lambda _chk, m=mode: self._set_analysis_mode(m))
            self._mode_radio[mode] = rb
        layout.addWidget(mode_group)

        dir_group = QGroupBox("Build Direction")
        dir_grid = QGridLayout(dir_group)
        dir_grid.setSpacing(3)
        for col, (label, vec) in enumerate([
            ("+X", (1, 0, 0)), ("-X", (-1, 0, 0)),
            ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0)),
            ("+Z", (0, 0, 1)), ("-Z", (0, 0, -1)),
        ]):
            row, c = divmod(col, 2)
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda _chk, v=vec: self._set_build_dir(v))
            dir_grid.addWidget(btn, row, c)
        layout.addWidget(dir_group)

        oh_group = QGroupBox("Overhang Settings")
        oh_layout = QGridLayout(oh_group)
        oh_layout.addWidget(QLabel("Threshold (deg):"), 0, 0)
        self._overhang_spin = QDoubleSpinBox()
        self._overhang_spin.setRange(1.0, 89.0)
        self._overhang_spin.setValue(45.0)
        self._overhang_spin.setSingleStep(5.0)
        self._overhang_spin.setDecimals(1)
        self._overhang_spin.valueChanged.connect(
            lambda _: self._refresh_analysis_if(AnalysisMode.OVERHANG)
        )
        oh_layout.addWidget(self._overhang_spin, 0, 1)
        layout.addWidget(oh_group)

        layer_group = QGroupBox("Layer Preview")
        layer_layout = QGridLayout(layer_group)
        layer_layout.addWidget(QLabel("Thickness (um):"), 0, 0)
        self._layer_thickness_spin = QSpinBox()
        self._layer_thickness_spin.setRange(10, 500)
        self._layer_thickness_spin.setValue(50)
        self._layer_thickness_spin.setSuffix(" um")
        self._layer_thickness_spin.valueChanged.connect(
            lambda _: self._rebuild_layer_slider()
        )
        layer_layout.addWidget(self._layer_thickness_spin, 0, 1)

        self._layer_slider = QSlider(Qt.Orientation.Horizontal)
        self._layer_slider.setRange(0, 0)
        self._layer_slider.setValue(0)
        self._layer_slider.valueChanged.connect(self._update_layer_preview)
        layer_layout.addWidget(self._layer_slider, 1, 0, 1, 2)

        self._layer_info_label = QLabel("Layer: - / -")
        layer_layout.addWidget(self._layer_info_label, 2, 0, 1, 2)

        self._layer_area_label = QLabel("Area: -")
        layer_layout.addWidget(self._layer_area_label, 3, 0, 1, 2)
        layout.addWidget(layer_group)

        wall_group = QGroupBox("Wall Thickness")
        wall_layout = QGridLayout(wall_group)
        wall_layout.addWidget(QLabel("Min target (mm):"), 0, 0)
        self._min_wall_spin = QDoubleSpinBox()
        self._min_wall_spin.setRange(0.01, 50.0)
        self._min_wall_spin.setValue(0.5)
        self._min_wall_spin.setDecimals(2)
        self._min_wall_spin.setSingleStep(0.1)
        wall_layout.addWidget(self._min_wall_spin, 0, 1)
        self._wall_progress_label = QLabel("")
        wall_layout.addWidget(self._wall_progress_label, 1, 0, 1, 2)
        layout.addWidget(wall_group)

        mesh_group = QGroupBox("Mesh Integrity")
        mesh_layout = QVBoxLayout(mesh_group)
        run_btn = QPushButton("Run Check")
        run_btn.clicked.connect(self._run_mesh_check)
        mesh_layout.addWidget(run_btn)
        self._mesh_result_edit = QTextEdit()
        self._mesh_result_edit.setReadOnly(True)
        self._mesh_result_edit.setMaximumHeight(110)
        self._mesh_result_edit.setPlainText("-")
        mesh_layout.addWidget(self._mesh_result_edit)
        layout.addWidget(mesh_group)

        layout.addStretch()
        return panel

    def _init_vtk(self) -> None:
        """Finalise VTK initialisation after the widget is shown."""
        try:
            self._vtk_widget._Iren.Initialize()
            self._vtk_widget.GetRenderWindow().Render()
        except Exception:
            logger.exception("VTK initialisation failed")
            self._set_status("VTK initialisation failed -- see log")

    def _set_status(self, message: str) -> None:
        """Update the status bar label and log the message.

        Parameters
        ----------
        message : str
            The status text to display and log.
        """
        self._status_label.setText(message)
        logger.debug("status: %s", message)

    def _snapshot(self, action: str) -> dict:
        """Create a serialisable snapshot of the current scene state.

        Parameters
        ----------
        action : str
            A label describing the action that prompted the snapshot
            (e.g. "Load model").

        Returns
        -------
        dict
            Dictionary containing all relevant scene state.
        """
        snap: dict = {
            "action": action,
            "file": self._current_file,
            "background": tuple(self._renderer.GetBackground()),
            "wireframe": self._wire_btn.isChecked(),
            "grid": self._grid_visible,
            "am_mode": self._am_mode.value,
            "build_dir": self._build_dir,
        }
        if self._actor is not None:
            snap["actor_props"] = _capture_actor_props(self._actor)
        return snap

    def _restore_snapshot(self, snap: dict) -> None:
        """Restore the scene from a snapshot.

        Parameters
        ----------
        snap : dict
            A snapshot dictionary as produced by ``_snapshot``.
        """
        if snap["file"]:
            self.load_model(snap["file"], add_undo=False)
        else:
            self._clear_actor()

        self._renderer.SetBackground(*snap["background"])

        if self._actor is not None and "actor_props" in snap:
            _apply_actor_props(self._actor, snap["actor_props"])
            wireframe = snap["actor_props"]["wireframe"]
            self._wire_btn.setChecked(wireframe)

        grid_state = snap.get("grid", False)
        self.show_grid(grid_state)
        self._grid_btn.setChecked(grid_state)

        self._build_dir = snap.get("build_dir", (0.0, 0.0, 1.0))
        am_mode_str = snap.get("am_mode", AnalysisMode.NONE.value)
        self._set_analysis_mode(AnalysisMode(am_mode_str))
        self._vtk_widget.GetRenderWindow().Render()

    def _push_undo(self, action: str) -> None:
        """Push a snapshot onto the undo stack and clear the redo stack.

        Parameters
        ----------
        action : str
            The action label for the undo snapshot.
        """
        self._undo_stack.append(self._snapshot(action))
        self._redo_stack.clear()

    def undo(self) -> None:
        """Undo the last action, if any."""
        if not self._undo_stack:
            self._set_status("Nothing to undo.")
            return
        self._redo_stack.append(self._snapshot("undo"))
        self._restore_snapshot(self._undo_stack.pop())
        self._set_status("Undone.")

    def redo(self) -> None:
        """Redo the last undone action, if any."""
        if not self._redo_stack:
            self._set_status("Nothing to redo.")
            return
        self._undo_stack.append(self._snapshot("redo"))
        self._restore_snapshot(self._redo_stack.pop())
        self._set_status("Redone.")

    def dragEnterEvent(self, event) -> None:
        """Accept drag events that contain file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        """Load the first dropped file URL."""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.load_model(path)
                break

    _READERS: Dict[str, type] = {
        ".stl": vtkSTLReader,
        ".ply": vtkPLYReader,
        ".obj": vtkOBJReader,
        ".vtp": vtkXMLPolyDataReader,
        ".vtk": vtkPolyDataReader,
    }

    @classmethod
    def _reader_for(cls, path: str):
        """Return an appropriate VTK reader for the given file extension.

        Parameters
        ----------
        path : str
            File path whose extension determines the reader type.

        Returns
        -------
        vtkAbstractPolyDataReader
            A configured VTK reader instance.
        """
        ext = Path(path).suffix.lower()
        reader_cls = cls._READERS.get(ext, vtkXMLPolyDataReader)
        reader = reader_cls()
        reader.SetFileName(str(path))
        return reader

    def open_file(self) -> None:
        """Present a file dialog and load the selected model."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open 3-D Model", os.getcwd(),
            "3-D Models (*.stl *.obj *.ply *.vtp *.vtk);;All Files (*.*)",
        )
        if path:
            self.load_model(path)

    def load_model(self, path: str, *, add_undo: bool = True) -> bool:
        """Load a 3‑D model from a file.

        Parameters
        ----------
        path : str
            Absolute path to the model file.
        add_undo : bool, optional
            If True, push the current state onto the undo stack before loading.
            Default is ``True``.

        Returns
        -------
        bool
            True if the model was loaded successfully, False otherwise.
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
        self._mode_radio[AnalysisMode.NONE].setChecked(True)

        self._set_status(f"Loading {os.path.basename(path)} ...")

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
        self._source_poly = tri.GetOutput()

        mapper = vtkPolyDataMapper()
        mapper.SetInputData(self._source_poly)

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(
            *_NAMED_COLORS.GetColor3d("LightSteelBlue"))
        actor.GetProperty().SetAmbient(0.2)
        actor.GetProperty().SetDiffuse(0.8)
        actor.GetProperty().SetSpecular(0.0)

        if self._actor is not None:
            self._renderer.RemoveActor(self._actor)

        self._mapper = mapper
        self._plain_mapper = mapper
        self._actor = actor
        self._current_file = path

        self._renderer.AddActor(actor)
        self._renderer.ResetCamera()
        self._renderer.ResetCameraClippingRange()

        self._update_cube_axes()

        self._wire_btn.setChecked(False)
        self._grid_btn.setChecked(self._grid_visible)
        self._mesh_result_edit.setPlainText("-")
        self._layer_info_label.setText("Layer: - / -")
        self._layer_area_label.setText("Area: -")

        self._vtk_widget.GetRenderWindow().Render()
        self._set_status(f"Loaded: {os.path.basename(path)}")
        self.model_loaded.emit(path)
        return True

    def _clear_actor(self) -> None:
        """Remove the current actor without emitting signals or history changes."""
        if self._actor is not None:
            self._renderer.RemoveActor(self._actor)
            self._actor = None
            self._mapper = None
            self._plain_mapper = None
            self._source_poly = None
            self._current_file = None
            self.show_grid(False)
            self._vtk_widget.GetRenderWindow().Render()

    def clear_model(self) -> None:
        """Clear the scene and reset all analysis state."""
        self._cancel_wall_worker()
        self._clear_am_overlays()
        if self._actor is not None:
            self._clear_actor()
            self._set_status("Model cleared.")
            self.model_cleared.emit()

    def reset_camera(self) -> None:
        """Reset the camera to show the whole model."""
        self._renderer.ResetCamera()
        self._renderer.ResetCameraClippingRange()
        if self._cube_axes is not None:
            self._cube_axes.SetCamera(self._renderer.GetActiveCamera())
        self._vtk_widget.GetRenderWindow().Render()
        self._set_status("Camera reset.")

    def _toggle_wireframe(self, checked: bool) -> None:
        """Toggle between wireframe and solid representation.

        Parameters
        ----------
        checked : bool
            True for wireframe, False for solid.
        """
        if self._actor is None:
            self._wire_btn.setChecked(False)
            return
        if checked:
            self._actor.GetProperty().SetRepresentationToWireframe()
        else:
            self._actor.GetProperty().SetRepresentationToSurface()
        self._vtk_widget.GetRenderWindow().Render()

    def _choose_background(self) -> None:
        """Open a colour picker and set the renderer background."""
        color = QColorDialog.getColor(parent=self)
        if not color.isValid():
            return
        self._renderer.SetBackground(
            color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0,
        )
        self._vtk_widget.GetRenderWindow().Render()

    def _screenshot(self) -> None:
        """Save a screenshot of the current view as a PNG file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", os.getcwd(), "PNG Image (*.png)"
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
        """Show or hide the bounding-box grid.

        Parameters
        ----------
        visible : bool
            If ``True``, the grid is shown (provided a model is loaded);
            otherwise it is hidden.
        """
        self._grid_visible = visible
        if self._cube_axes is not None:
            self._cube_axes.SetVisibility(visible)
            self._grid_btn.setChecked(visible)
            self._vtk_widget.GetRenderWindow().Render()

    def toggle_grid(self) -> None:
        """Toggle the grid visibility on or off."""
        self.show_grid(not self._grid_visible)

    def _update_cube_axes(self) -> None:
        """Create or update the cube‑axes actor to match the current model bounds."""
        if self._source_poly is None:
            return
        bounds = self._source_poly.GetBounds()
        camera = self._renderer.GetActiveCamera()

        if self._cube_axes is None:
            self._cube_axes = vtkCubeAxesActor()
            self._cube_axes.SetFlyModeToOuterEdges()
            self._cube_axes.SetCamera(camera)
            self._cube_axes.SetXAxisLabelVisibility(True)
            self._cube_axes.SetYAxisLabelVisibility(True)
            self._cube_axes.SetZAxisLabelVisibility(True)
            self._cube_axes.SetXAxisTickVisibility(True)
            self._cube_axes.SetYAxisTickVisibility(True)
            self._cube_axes.SetZAxisTickVisibility(True)
            self._cube_axes.SetLabelScaling(False, False, False, False)
            self._cube_axes.GetXAxesGridlinesProperty().SetColor(0.6, 0.6, 0.6)
            self._cube_axes.GetYAxesGridlinesProperty().SetColor(0.6, 0.6, 0.6)
            self._cube_axes.GetZAxesGridlinesProperty().SetColor(0.6, 0.6, 0.6)
            self._renderer.AddActor(self._cube_axes)
        else:
            self._cube_axes.SetCamera(camera)

        self._cube_axes.SetBounds(bounds)
        self._cube_axes.SetVisibility(self._grid_visible)

    def _show_lighting_dialog(self) -> None:
        """Open the lighting controls dialog."""
        if self._actor is None:
            self._set_status("No model loaded.")
            return
        LightingDialog(self._actor, self._vtk_widget.GetRenderWindow(),
                       self).exec()

    def _show_statistics_dialog(self) -> None:
        """Open the model statistics dialog."""
        StatisticsDialog(self._actor, self).exec()

    _FILTER_EXT: Dict[str, str] = {
        "*.stl": ".stl", "*.obj": ".obj", "*.ply": ".ply", "*.vtk": ".vtk",
    }

    def _show_export_dialog(self) -> None:
        """Show the export file dialog and call _export_model."""
        if self._actor is None:
            self._set_status("No model loaded.")
            return
        path, sel = QFileDialog.getSaveFileName(
            self, "Export Model", os.getcwd(),
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
        """Write the current model to path in the format inferred from its extension.

        Parameters
        ----------
        path : str
            Output file path.
        """
        if self._source_poly is None:
            self._set_status("Nothing to export.")
            return
        ext = Path(path).suffix.lower()
        try:
            if ext == ".stl":
                w = vtkSTLWriter()
                w.SetFileName(path)
                w.SetInputData(self._source_poly)
                w.Write()
            elif ext == ".obj":
                prefix = str(Path(path).with_suffix(""))
                exp = vtkOBJExporter()
                exp.SetRenderWindow(self._vtk_widget.GetRenderWindow())
                exp.SetFilePrefix(prefix)
                exp.Write()
            elif ext == ".ply":
                w = vtkPLYWriter()
                w.SetFileName(path)
                w.SetInputData(self._source_poly)
                w.Write()
            else:
                w = vtkPolyDataWriter()
                w.SetFileName(path)
                w.SetInputData(self._source_poly)
                w.Write()
            self._set_status(f"Exported: {os.path.basename(path)}")
        except Exception:
            logger.exception("Export failed for %s", path)
            self._set_status("Export failed -- see log.")

    def _set_build_dir(self, vec: Tuple[float, float, float]) -> None:
        """Set the active build direction and refresh the current analysis.

        Parameters
        ----------
        vec : tuple of float
            New build direction vector (e.g. (0, 0, 1) for +Z).
        """
        self._build_dir = vec
        self._refresh_analysis_if(self._am_mode)
        self._set_status(f"Build direction: {vec}")

    def _refresh_analysis_if(self, mode: AnalysisMode) -> None:
        """Re-run the analysis only if mode matches the active one.

        Parameters
        ----------
        mode : AnalysisMode
            Analysis mode to refresh.
        """
        if self._am_mode == mode:
            self._set_analysis_mode(mode)

    def _set_analysis_mode(self, mode: AnalysisMode) -> None:
        """Switch to a different analysis mode, clearing previous overlays.

        Parameters
        ----------
        mode : AnalysisMode
            The new analysis mode.
        """
        if self._actor is None and mode != AnalysisMode.NONE:
            self._set_status("Load a model first.")
            self._mode_radio[AnalysisMode.NONE].setChecked(True)
            return

        if mode != AnalysisMode.WALL:
            self._cancel_wall_worker()

        self._clear_am_overlays()
        self._restore_plain_actor()
        self._am_mode = mode
        self._mode_radio[mode].setChecked(True)

        dispatch = {
            AnalysisMode.NONE: lambda: None,
            AnalysisMode.OVERHANG: self._run_overhang_analysis,
            AnalysisMode.WALL: self._start_wall_thickness,
            AnalysisMode.LAYER: self._setup_layer_preview,
            AnalysisMode.SUPPORT: self._run_support_estimate,
        }
        dispatch[mode]()

    def _clear_am_overlays(self) -> None:
        """Remove all AM overlay actors and the scalar bar from the renderer."""
        for actor in self._am_overlays:
            self._renderer.RemoveActor(actor)
        self._am_overlays.clear()

        if self._mesh_check_actor is not None:
            self._renderer.RemoveActor(self._mesh_check_actor)
            self._mesh_check_actor = None

        self._hide_scalar_bar()

    def _restore_plain_actor(self) -> None:
        """Reset the main actor to its neutral, non-analysis appearance."""
        if self._actor is None:
            return
        if self._plain_mapper is not None:
            self._plain_mapper.ScalarVisibilityOff()
            self._actor.SetMapper(self._plain_mapper)
            self._mapper = self._plain_mapper
        prop = self._actor.GetProperty()
        prop.SetColor(*_NAMED_COLORS.GetColor3d("LightSteelBlue"))
        prop.SetOpacity(1.0)
        prop.SetAmbient(0.2)
        prop.SetDiffuse(0.8)
        prop.SetSpecular(0.0)
        if self._wire_btn.isChecked():
            prop.SetRepresentationToWireframe()
        else:
            prop.SetRepresentationToSurface()

    def _show_scalar_bar(self, title: str, lut: vtkLookupTable) -> None:
        """Display a scalar bar on the right side of the viewport.

        Parameters
        ----------
        title : str
            Title for the scalar bar.
        lut : vtkLookupTable
            Lookup table to use for colors.
        """
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
        self._renderer.AddActor2D(bar)

    def _hide_scalar_bar(self) -> None:
        """Remove the scalar bar if one is currently shown."""
        if self._scalar_bar is not None:
            self._renderer.RemoveActor2D(self._scalar_bar)
            self._scalar_bar = None

    def _run_mesh_check(self) -> None:
        """Identify boundary and non-manifold edges, highlighting them in red."""
        if self._source_poly is None:
            self._mesh_result_edit.setPlainText("No model loaded.")
            return

        pd = self._source_poly

        def _edge_filter(boundary: bool, non_manifold: bool) -> vtkFeatureEdges:
            f = vtkFeatureEdges()
            f.SetInputData(pd)
            f.SetBoundaryEdges(boundary)
            f.SetNonManifoldEdges(non_manifold)
            f.SetManifoldEdges(False)
            f.SetFeatureEdges(False)
            f.ColoringOff()
            f.Update()
            return f

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
            "PASS  No open boundaries" if n_boundary == 0
            else f"FAIL  Open boundaries: {n_boundary} pts"
        )
        if n_boundary > 0:
            issues = True

        lines.append(
            "PASS  No non-manifold edges" if n_nm == 0
            else f"FAIL  Non-manifold edges: {n_nm} pts"
        )
        if n_nm > 0:
            issues = True

        lines += ["",
                  "Overall: PASS" if not issues else "Overall: ISSUES FOUND"]
        self._mesh_result_edit.setPlainText("\n".join(lines))

        if self._mesh_check_actor is not None:
            self._renderer.RemoveActor(self._mesh_check_actor)
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
            self._renderer.AddActor(bad_actor)
            self._vtk_widget.GetRenderWindow().Render()

        n_issues = int(n_boundary > 0) + int(n_nm > 0)
        self._set_status(
            "Mesh check: PASS" if not issues
            else f"Mesh check: {n_issues} issue(s) found"
        )

    def _run_overhang_analysis(self) -> None:
        """Colour each face by its overhang angle using a green‑orange‑red LUT."""
        if self._source_poly is None:
            return

        try:
            angles, _ = _compute_cell_angles(self._source_poly, self._build_dir)
        except RuntimeError as e:
            self._set_status(str(e))
            return

        threshold = 90.0 + self._overhang_spin.value()
        lut = _make_overhang_lut(threshold)

        pd = vtkPolyData()
        pd.ShallowCopy(self._source_poly)
        scalars = numpy_to_vtk(angles, deep=True)
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
        self._vtk_widget.GetRenderWindow().Render()

        n_critical = int(np.sum(angles > threshold))
        pct = 100 * n_critical / max(len(angles), 1)
        self._set_status(
            f"Overhang: {n_critical} critical cells ({pct:.1f}%) -- "
            f"threshold {self._overhang_spin.value():.0f} deg from horizontal"
        )

    def _start_wall_thickness(self) -> None:
        """Launch the background wall-thickness computation."""
        if self._source_poly is None:
            return
        self._cancel_wall_worker()
        self._wall_progress_label.setText("Computing...  0%")

        worker = _WallThicknessWorker(self._source_poly)
        worker.progress.connect(
            lambda p: self._wall_progress_label.setText(f"Computing... {p}%")
        )
        worker.result.connect(self._on_wall_thickness_result)
        worker.error.connect(self._on_wall_thickness_error)
        self._wall_worker = worker
        worker.start()

    def _cancel_wall_worker(self) -> None:
        """Gracefully cancel and wait for the wall thickness worker."""
        if self._wall_worker is not None and self._wall_worker.isRunning():
            self._wall_worker.cancel()
            self._wall_worker.wait()
        self._wall_worker = None
        self._wall_progress_label.setText("")

    def _on_wall_thickness_result(self, thicknesses: np.ndarray) -> None:
        """Slot for wall thickness results; updates the actor's colouring.

        Parameters
        ----------
        thicknesses : ndarray of float32
            Per-point wall thickness values.
        """
        self._wall_progress_label.setText("")
        if self._am_mode != AnalysisMode.WALL or self._actor is None:
            return

        pd = vtkPolyData()
        pd.ShallowCopy(self._source_poly)

        valid = thicknesses[thicknesses < thicknesses.max()]
        min_t = float(valid.min()) if len(valid) else 0.0
        max_t = float(np.percentile(thicknesses, 95))

        scalars = numpy_to_vtk(
            np.clip(thicknesses, min_t, max_t).astype(np.float32), deep=True
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
        self._vtk_widget.GetRenderWindow().Render()

        min_wall = self._min_wall_spin.value()
        n_thin = int(np.sum(thicknesses < min_wall))
        pct = 100 * n_thin / max(len(thicknesses), 1)
        self._set_status(
            f"Wall thickness: {n_thin} thin points ({pct:.1f}%) "
            f"below {min_wall:.2f} mm target  |  "
            f"range {min_t:.2f}-{max_t:.2f} mm"
        )

    def _on_wall_thickness_error(self, msg: str) -> None:
        """Slot for wall thickness computation errors.

        Parameters
        ----------
        msg : str
            Error message.
        """
        self._wall_progress_label.setText("")
        self._set_status(f"Wall thickness error: {msg}")

    def _setup_layer_preview(self) -> None:
        """Enter layer preview mode: rebuild the slider and show layer 0."""
        if self._source_poly is None:
            return
        self._actor.GetProperty().SetOpacity(0.22)
        self._rebuild_layer_slider()
        self._update_layer_preview(self._layer_slider.value())

    def _rebuild_layer_slider(self) -> None:
        """Recalculate the number of layers based on model height and thickness."""
        if self._source_poly is None:
            return
        _, height = _model_base_and_height(
            self._source_poly.GetBounds(), self._build_dir
        )
        thickness = self._layer_thickness_spin.value() / 1000.0
        n_layers = max(1, int(math.ceil(height / thickness)))
        prev = self._layer_slider.value()
        self._layer_slider.setRange(0, n_layers - 1)
        self._layer_slider.setValue(min(prev, n_layers - 1))

    def _update_layer_preview(self, layer_idx: int) -> None:
        """Show the cross-section of one layer and its area.

        Parameters
        ----------
        layer_idx : int
            Zero-based layer index to display.
        """
        if self._am_mode != AnalysisMode.LAYER or self._source_poly is None:
            return

        for actor in self._am_overlays:
            self._renderer.RemoveActor(actor)
        self._am_overlays.clear()

        thickness = self._layer_thickness_spin.value() / 1000.0
        build = np.array(self._build_dir, dtype=float)
        build /= np.linalg.norm(build)

        base_h, _ = _model_base_and_height(
            self._source_poly.GetBounds(), self._build_dir
        )
        layer_h = base_h + (layer_idx + 1) * thickness
        origin = (build * layer_h).tolist()
        n_layers = self._layer_slider.maximum() + 1

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
        self._renderer.AddActor(section_actor)

        area = 0.0
        try:
            for i in range(filled_pd.GetNumberOfCells()):
                cell = filled_pd.GetCell(i)
                if cell.GetNumberOfPoints() == 3:
                    p0 = np.array(filled_pd.GetPoint(cell.GetPointId(0)))
                    p1 = np.array(filled_pd.GetPoint(cell.GetPointId(1)))
                    p2 = np.array(filled_pd.GetPoint(cell.GetPointId(2)))
                    area += 0.5 * float(
                        np.linalg.norm(np.cross(p1 - p0, p2 - p0)))
        except Exception:
            logger.warning(
                "Layer preview: could not compute cross-section area")

        self._layer_info_label.setText(f"Layer: {layer_idx + 1} / {n_layers}")
        self._layer_area_label.setText(f"Area: {area:.2f} mm\u00B2")
        self._vtk_widget.GetRenderWindow().Render()
        self._set_status(
            f"Layer {layer_idx + 1}/{n_layers}  "
            f"h={layer_h:.3f} mm  area={area:.2f} mm\u00B2"
        )

    def _run_support_estimate(self) -> None:
        """Highlight overhanging faces and estimate support volume."""
        if self._source_poly is None:
            return

        try:
            angles, _ = _compute_cell_angles(self._source_poly, self._build_dir)
        except RuntimeError as e:
            self._set_status(str(e))
            return

        threshold = 90.0 + self._overhang_spin.value()
        overhang_mask = angles > threshold

        if not np.any(overhang_mask):
            self._set_status("Support: no overhanging faces detected.")
            return

        self._actor.GetProperty().SetOpacity(0.28)
        self._actor.GetProperty().SetColor(*_NAMED_COLORS.GetColor3d("Silver"))

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
        self._renderer.AddActor(oh_actor)

        base_h, _ = _model_base_and_height(
            self._source_poly.GetBounds(), self._build_dir
        )
        build = np.array(self._build_dir, dtype=np.float64)
        build /= np.linalg.norm(build)
        total_vol = 0.0
        total_area = 0.0
        pd = self._source_poly

        for cell_id in np.where(overhang_mask)[0]:
            cell = pd.GetCell(int(cell_id))
            n_pts = cell.GetNumberOfPoints()
            if n_pts < 3:
                continue
            pts_arr = np.array([pd.GetPoint(cell.GetPointId(i))
                                for i in range(n_pts)])
            centroid = pts_arr.mean(axis=0)
            h = max(0.0, float(np.dot(centroid, build)) - base_h)
            v0 = pts_arr[1] - pts_arr[0]
            v1 = pts_arr[2] - pts_arr[0]
            cell_area = 0.5 * float(np.linalg.norm(np.cross(v0, v1)))
            total_area += cell_area
            total_vol += cell_area * h

        self._vtk_widget.GetRenderWindow().Render()
        self._set_status(
            f"Support: {int(np.sum(overhang_mask))} overhanging cells  |  "
            f"projected area {total_area:.1f} mm\u00B2  |  "
            f"estimated support vol ~{total_vol:.1f} mm\u00B3"
        )

    def cleanup(self) -> None:
        """Release all VTK and Qt resources, making the widget safe to discard."""
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True
        logger.debug("ModelViewerWidget.cleanup() called")

        try:
            self._cancel_wall_worker()
        except Exception:
            logger.exception("cleanup: error cancelling wall worker")

        try:
            self._ori_marker.SetEnabled(0)
            self._ori_marker.SetInteractor(None)
        except Exception:
            logger.exception("cleanup: error disabling orientation marker")

        try:
            self._clear_am_overlays()
        except Exception:
            logger.exception("cleanup: error clearing AM overlays")

        if self._cube_axes is not None:
            try:
                self._renderer.RemoveActor(self._cube_axes)
            except Exception:
                logger.exception("cleanup: error removing cube axes")
            self._cube_axes = None

        try:
            if self._actor is not None:
                self._renderer.RemoveActor(self._actor)
            self._renderer.RemoveAllLights()
            self._renderer.Clear()
        except Exception:
            logger.exception("cleanup: error clearing renderer")

        self._actor = None
        self._mapper = None
        self._plain_mapper = None
        self._source_poly = None
        self._current_file = None

        try:
            rw = self._vtk_widget.GetRenderWindow()
            rw.Finalize()
            self._vtk_widget._Iren.TerminateApp()
        except Exception:
            logger.exception("cleanup: error finalising render window")

        try:
            self._vtk_widget.Finalize()
        except Exception:
            logger.exception("cleanup: error finalising VTK widget")

        self._renderer = None
        self._ori_marker = None
        self._undo_stack.clear()
        self._redo_stack.clear()

        logger.debug("ModelViewerWidget.cleanup() complete")

    def closeEvent(self, event) -> None:
        """Handle a close event by finalising resources."""
        self.cleanup()
        event.accept()