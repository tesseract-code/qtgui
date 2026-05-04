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
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QSurfaceFormat, QIcon, QPixmap, QImage
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
    QToolButton, QToolBar,
)
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

from qtgui.pixmap import colorize_pixmap

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


# ---------- off‑screen VTK widget (no X11 windows) ----------
class OffscreenVTKWidget(QWidget):
    """QWidget that renders VTK completely off‑screen and shows the result via QLabel.

    Exposes the same minimal interface that ModelViewerWidget expects:
    - GetRenderWindow() -> vtkRenderWindow
    - _Iren                -> vtkRenderWindowInteractor
    - Finalize()           -> clean VTK resources
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)

        # ----- VTK off‑screen pipeline -----
        self._render_window = vtk.vtkRenderWindow()
        self._render_window.OffScreenRenderingOn()   # NO X11 window ever created
        # Initial size – will be corrected in resizeEvent / showEvent
        self._render_window.SetSize(self.width(), self.height())

        self._interactor = vtk.vtkRenderWindowInteractor()
        self._interactor.SetRenderWindow(self._render_window)
        self._interactor.Initialize()

        self._w2i = vtk.vtkWindowToImageFilter()
        self._w2i.SetInput(self._render_window)
        self._w2i.SetScale(1)

        # ----- Display label -----
        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ----- Mouse tracking -----
        self.setMouseTracking(True)
        self._last_pos = None

        # Ensure the render window size is correct before the first render
        self._sync_render_window_size()

    # ---------- Public API expected by ModelViewerWidget ----------
    @property
    def _Iren(self):
        """Compatibility name for the VTK interactor."""
        return self._interactor

    def GetRenderWindow(self):
        """Return the VTK render window (already off‑screen)."""
        return self._render_window

    def Finalize(self):
        """Clean up VTK objects when the widget is destroyed."""
        try:
            self._interactor.TerminateApp()
        except Exception:
            pass
        try:
            self._render_window.Finalize()
        except Exception:
            pass

    # ----- Qt overrides -----
    def resizeEvent(self, event):
        """Keep the render buffer and label in sync with the widget."""
        self._sync_render_window_size()
        self._image_label.resize(self.size())
        self._update_image()
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        # Ensure the first frame is rendered once the widget is visible.
        self._sync_render_window_size()
        self._update_image()

    def paintEvent(self, event):
        # The label handles painting; we just trigger a refresh if needed.
        pass

    def _sync_render_window_size(self):
        """Make the off‑screen buffer exactly match the widget’s pixel size."""
        w = self.width()
        h = self.height()
        if w > 0 and h > 0:
            self._render_window.SetSize(w, h)

    # ----- Image generation -----
    def _update_image(self):
        """Render the VTK scene and transfer it to the QLabel (no scaling)."""
        # Only render if a renderer exists (added later by parent)
        if not self._render_window.GetRenderers().GetNumberOfItems():
            return

        # Make sure the render window size is current
        self._sync_render_window_size()

        self._render_window.Render()
        self._w2i.Modified()
        self._w2i.Update()
        image_data = self._w2i.GetOutput()

        width, height, _ = image_data.GetDimensions()
        ncomp = image_data.GetNumberOfScalarComponents()
        if ncomp in (3, 4):
            arr = vtk_to_numpy(image_data.GetPointData().GetScalars())
            arr = arr.reshape(height, width, ncomp)
            if ncomp == 4:
                arr = arr[:, :, :3]  # drop alpha

            # VTK puts origin at bottom-left; Qt expects top-left → flip vertically
            arr = np.flipud(arr)
            # Make the array contiguous, as QImage requires a contiguous byte buffer
            arr = np.ascontiguousarray(arr)

            h, w, _ = arr.shape
            bytes_per_line = 3 * w
            # Pass the data as bytes to match QImage(data: bytes, width, height, bytesPerLine, format)
            qim = QImage(bytes(arr.data), w, h, bytes_per_line,
                         QImage.Format.Format_RGB888)

            # Use the image directly – no scaling – for pixel‑perfect display
            pixmap = QPixmap.fromImage(qim)
            self._image_label.setPixmap(pixmap)
            self._image_label.setFixedSize(pixmap.size())

    # ----- Mouse / keyboard → VTK interactor -----
    def _event_position_xy(self, event):
        pos = event.position()
        return int(pos.x()), int(pos.y())

    def mousePressEvent(self, event):
        x, y = self._event_position_xy(event)
        self._last_pos = event.pos()
        self._interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        btn = event.button()
        if btn == Qt.MouseButton.LeftButton:
            self._interactor.LeftButtonPressEvent()
        elif btn == Qt.MouseButton.RightButton:
            self._interactor.RightButtonPressEvent()
        elif btn == Qt.MouseButton.MiddleButton:
            self._interactor.MiddleButtonPressEvent()
        self._update_image()

    def mouseReleaseEvent(self, event):
        x, y = self._event_position_xy(event)
        self._last_pos = event.pos()
        self._interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        btn = event.button()
        if btn == Qt.MouseButton.LeftButton:
            self._interactor.LeftButtonReleaseEvent()
        elif btn == Qt.MouseButton.RightButton:
            self._interactor.RightButtonReleaseEvent()
        elif btn == Qt.MouseButton.MiddleButton:
            self._interactor.MiddleButtonReleaseEvent()
        self._update_image()

    def mouseMoveEvent(self, event):
        if self._last_pos is None:
            return
        x, y = self._event_position_xy(event)
        self._interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        self._interactor.MouseMoveEvent()
        self._update_image()

    def wheelEvent(self, event):
        pos = event.position()
        x, y = int(pos.x()), int(pos.y())
        self._interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        if event.angleDelta().y() > 0:
            self._interactor.MouseWheelForwardEvent()
        else:
            self._interactor.MouseWheelBackwardEvent()
        self._update_image()

    def keyPressEvent(self, event):
        pos = event.position() if hasattr(event, 'position') else event.pos()
        x, y = int(pos.x()), int(pos.y())
        self._interactor.SetEventInformation(x, y, 0, 0, event.text(), 0, None)
        self._interactor.KeyPressEvent()
        self._update_image()

    def keyReleaseEvent(self, event):
        pos = event.position() if hasattr(event, 'position') else event.pos()
        x, y = int(pos.x()), int(pos.y())
        self._interactor.SetEventInformation(x, y, 0, 0, event.text(), 0, None)
        self._interactor.KeyReleaseEvent()
        self._update_image()


# ---------- helper functions for AM analyses ----------
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
    def __init__(self, actor: vtkActor, render_callback=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lighting Controls")
        self.setFixedSize(320, 185)
        self._actor = actor
        self._render = render_callback if render_callback else (lambda: None)

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
        prop = self._actor.GetProperty()
        prop.SetAmbient(self._spinboxes["ambient"].value())
        prop.SetDiffuse(self._spinboxes["diffuse"].value())
        prop.SetSpecular(self._spinboxes["specular"].value())
        self._render()  # uses the callback to update the off‑screen widget


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


import os
import math
from collections import deque
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QColorDialog, QDoubleSpinBox, QFileDialog, QGridLayout,
    QGroupBox, QLabel, QPushButton, QRadioButton, QSlider, QSpinBox,
    QSplitter, QTextEdit, QToolBar, QToolButton, QVBoxLayout, QWidget,
)
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkLookupTable, vtkMath
from vtkmodules.vtkCommonDataModel import vtkPolyData
from vtkmodules.vtkFiltersCore import (
    vtkAppendPolyData,  vtkCutter, vtkFeatureEdges,
    vtkTriangleFilter,
)
from vtkmodules.vtkFiltersSources import vtkPlaneSource
from vtkmodules.vtkIOImage import vtkPNGWriter
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor, vtkCubeAxesActor, vtkScalarBarActor
from vtkmodules.vtkRenderingCore import (
    vtkActor, vtkPolyDataMapper, vtkRenderer, vtkWindowToImageFilter,
)
from vtkmodules.vtkRenderingOpenGL2 import vtkOpenGLRenderer
from vtkmodules.util.numpy_support import numpy_to_vtk

_NAMED_COLORS = vtkNamedColors()
logger = logging.getLogger(__name__)


class _UndoManager:
    """Manages undo/redo stacks using scene snapshots."""

    def __init__(self, maxlen: int):
        self._undo_stack: deque[dict] = deque(maxlen=maxlen)
        self._redo_stack: deque[dict] = deque(maxlen=maxlen)

    def push(self, snapshot: dict) -> None:
        """Store a snapshot and clear the redo stack."""
        self._undo_stack.append(snapshot)
        self._redo_stack.clear()

    def undo(self, current_snapshot: dict) -> Optional[dict]:
        """Pop from undo stack, push current on redo, return snapshot to restore."""
        if not self._undo_stack:
            return None
        self._redo_stack.append(current_snapshot)
        return self._undo_stack.pop()

    def redo(self, current_snapshot: dict) -> Optional[dict]:
        """Pop from redo stack, push current on undo, return snapshot to restore."""
        if not self._redo_stack:
            return None
        self._undo_stack.append(current_snapshot)
        return self._redo_stack.pop()

    @property
    def undo_stack(self) -> deque:
        return self._undo_stack

    @property
    def redo_stack(self) -> deque:
        return self._redo_stack

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()


class _VTKViewport:
    """Encapsulates VTK rendering: renderer, camera, orientation marker, grid."""

    def __init__(self, vtk_widget: OffscreenVTKWidget):
        self._vtk_widget = vtk_widget
        self._renderer: Optional[vtkRenderer] = None
        self._ori_marker: Optional[vtkOrientationMarkerWidget] = None
        self._cube_axes: Optional[vtkCubeAxesActor] = None
        self._grid_visible = False

    def initialize(self) -> None:
        ren = vtkRenderer()
        self._vtk_widget.GetRenderWindow().AddRenderer(ren)
        ren.SetBackground(_NAMED_COLORS.GetColor3d("SlateGray"))
        self._renderer = ren

        style = vtkInteractorStyleTrackballCamera()
        self._vtk_widget._Iren.SetInteractorStyle(style)

        axes = vtkAxesActor()
        self._ori_marker = vtkOrientationMarkerWidget()
        self._ori_marker.SetInteractor(self._vtk_widget._Iren)
        self._ori_marker.SetOrientationMarker(axes)
        self._ori_marker.SetEnabled(1)
        self._ori_marker.InteractiveOn()
        self._update_image()

    @property
    def renderer(self) -> vtkRenderer:
        return self._renderer

    @property
    def widget(self) -> OffscreenVTKWidget:
        return self._vtk_widget

    def _update_image(self) -> None:
        self._vtk_widget._update_image()

    def add_actor(self, actor: vtkActor) -> None:
        self._renderer.AddActor(actor)

    def remove_actor(self, actor: vtkActor) -> None:
        self._renderer.RemoveActor(actor)

    def add_actor2d(self, actor) -> None:
        self._renderer.AddActor2D(actor)

    def remove_actor2d(self, actor) -> None:
        self._renderer.RemoveActor2D(actor)

    def reset_camera(self) -> None:
        if self._cube_axes is not None:
            self._cube_axes.SetCamera(self._renderer.GetActiveCamera())
        self._renderer.ResetCamera()
        self._renderer.ResetCameraClippingRange()
        self._update_image()

    def set_background(self, r: float, g: float, b: float) -> None:
        self._renderer.SetBackground(r, g, b)
        self._update_image()

    def get_background(self) -> Tuple[float, float, float]:
        return self._renderer.GetBackground()

    def show_grid(self, visible: bool) -> None:
        self._grid_visible = visible
        if self._cube_axes is not None:
            self._cube_axes.SetVisibility(visible)
            self._update_image()

    def update_grid(self, polydata: vtkPolyData) -> None:
        if polydata is None:
            return
        bounds = polydata.GetBounds()
        camera = self._renderer.GetActiveCamera()
        if self._cube_axes is None:
            ca = vtkCubeAxesActor()
            ca.SetFlyModeToOuterEdges()
            ca.SetCamera(camera)
            ca.SetXAxisLabelVisibility(True)
            ca.SetYAxisLabelVisibility(True)
            ca.SetZAxisLabelVisibility(True)
            ca.SetXAxisTickVisibility(True)
            ca.SetYAxisTickVisibility(True)
            ca.SetZAxisTickVisibility(True)
            ca.SetLabelScaling(False, False, False, False)
            ca.GetXAxesGridlinesProperty().SetColor(0.6, 0.6, 0.6)
            ca.GetYAxesGridlinesProperty().SetColor(0.6, 0.6, 0.6)
            ca.GetZAxesGridlinesProperty().SetColor(0.6, 0.6, 0.6)
            self._renderer.AddActor(ca)
            self._cube_axes = ca
        else:
            self._cube_axes.SetCamera(camera)
        self._cube_axes.SetBounds(bounds)
        self._cube_axes.SetVisibility(self._grid_visible)

    def remove_cube_axes(self) -> None:
        if self._cube_axes is not None:
            self._renderer.RemoveActor(self._cube_axes)
            self._cube_axes = None

    def cleanup(self) -> None:
        if self._ori_marker:
            self._ori_marker.SetEnabled(0)
            self._ori_marker.SetInteractor(None)
        self.remove_cube_axes()
        self._renderer.RemoveAllViewProps()
        self._renderer.Clear()
        self._vtk_widget.Finalize()
        self._renderer = None
        self._ori_marker = None

    def render(self) -> None:
        self._update_image()


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
        def _btn(label, slot, icon_path):
            b = QToolButton()
            b.setToolTip(label)
            b.setIcon(QIcon(colorize_pixmap(QPixmap(icon_path),
                                            self.palette().highlightedText().color())))
            b.clicked.connect(slot)
            self.addWidget(b)
            return b

        _btn("Open", self.openRequested.emit, "line-icons:file-add-line.svg")
        _btn("Export", self.exportRequested.emit, "line-icons:export-line.svg")
        self.addSeparator()
        _btn("Reset Camera", self.resetCameraRequested.emit, "line-icons:camera-switch-line.svg")

        self._wire_btn.setCheckable(True)
        self._wire_btn.setIcon(QIcon(colorize_pixmap(QPixmap("line-icons:global-line.svg"),
                                                     self.palette().highlightedText().color())))
        self._wire_btn.setToolTip("Toggle wireframe/solid")
        self._wire_btn.toggled.connect(self.wireframeToggled.emit)
        self.addWidget(self._wire_btn)

        self._grid_btn.setCheckable(True)
        self._grid_btn.setIcon(QIcon(colorize_pixmap(QPixmap("line-icons:grid-line.svg"),
                                                     self.palette().highlightedText().color())))
        self._grid_btn.setToolTip("Toggle bounding-box grid")
        self._grid_btn.toggled.connect(self.gridToggled.emit)
        self.addWidget(self._grid_btn)

        _btn("Background", self.backgroundChangeRequested.emit, "line-icons:multi-image-line.svg")
        self.addSeparator()
        _btn("Lighting", self.lightingRequested.emit, "line-icons:lightbulb-line.svg")
        _btn("Statistics", self.statisticsRequested.emit, "line-icons:donut-chart-line.svg")
        _btn("Screenshot", self.screenshotRequested.emit, "line-icons:camera-lens-line.svg")
        self.addSeparator()
        _btn("Undo", self.undoRequested.emit, "line-icons:arrow-go-back-line.svg")
        _btn("Redo", self.redoRequested.emit, "line-icons:arrow-go-forward-line.svg")
        self.addSeparator()
        self.addWidget(self._status_label)

    @property
    def wire_btn(self) -> QToolButton:
        return self._wire_btn

    @property
    def grid_btn(self) -> QToolButton:
        return self._grid_btn

    @property
    def status_label(self) -> QLabel:
        return self._status_label


class AnalysisPanel(QWidget):
    """Right‑hand analysis panel. Exposes child widgets for backward compatibility."""

    modeChanged = pyqtSignal(object)          # AnalysisMode
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
        self._dir_button_group.buttonClicked.connect(self._on_dir_button_clicked)
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
        self._overhang_spin.valueChanged.connect(self.overhangThresholdChanged.emit)
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
        super().__init__(parent)
        self._actor: Optional[vtkActor] = None
        self._mapper: Optional[vtkPolyDataMapper] = None
        self._plain_mapper: Optional[vtkPolyDataMapper] = None
        self._source_poly: Optional[vtkPolyData] = None
        self._current_file: Optional[str] = None

        self._undo_manager = _UndoManager(self._MAX_HISTORY)
        # Backward compatibility: expose the undo stacks
        self._undo_stack = self._undo_manager.undo_stack
        self._redo_stack = self._undo_manager.redo_stack

        self._am_mode: AnalysisMode = AnalysisMode.NONE
        self._build_dir: Tuple[float, float, float] = (0.0, 0.0, 1.0)
        self._am_overlays: list = []
        self._scalar_bar: Optional[vtkScalarBarActor] = None
        self._mesh_check_actor: Optional[vtkActor] = None
        self._wall_worker: Optional[_WallThicknessWorker] = None

        self._grid_visible: bool = False
        self._cube_axes: Optional[vtkCubeAxesActor] = None

        self._viewport: Optional[_VTKViewport] = None
        self._renderer: Optional[vtkRenderer] = None
        self._ori_marker: Optional[vtkOrientationMarkerWidget] = None

        self._setup_ui()
        QTimer.singleShot(500, self._init_vtk)

    # ----------------------------------------------------------------------
    # UI construction (delegated to sub‑widgets but keeping backward‑compat)
    # ----------------------------------------------------------------------
    def _setup_ui(self) -> None:
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

        # Expose buttons and status label for backward compatibility
        self._wire_btn = self._toolbar.wire_btn
        self._grid_btn = self._toolbar.grid_btn
        self._status_label = self._toolbar.status_label

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        self._vtk_widget = OffscreenVTKWidget(self)
        self._viewport = _VTKViewport(self._vtk_widget)
        splitter.addWidget(self._vtk_widget)

        self._am_panel = AnalysisPanel(self)
        splitter.addWidget(self._am_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, 240])

        # Connect analysis panel signals
        self._am_panel.modeChanged.connect(
            lambda m: self._set_analysis_mode(m))
        self._am_panel.buildDirectionChanged.connect(self._set_build_dir)
        self._am_panel.overhangThresholdChanged.connect(
            lambda: self._refresh_analysis_if(AnalysisMode.OVERHANG))
        self._am_panel.layerThicknessChanged.connect(self._rebuild_layer_slider)
        self._am_panel.layerSliderChanged.connect(self._update_layer_preview)
        self._am_panel.minWallChanged.connect(
            lambda: self._set_analysis_mode(AnalysisMode.WALL))
        self._am_panel.meshCheckRequested.connect(self._run_mesh_check)

        # Backward compatibility: assign panel child widgets to self
        self._overhang_spin = self._am_panel.overhang_spin
        self._layer_thickness_spin = self._am_panel.layer_thickness_spin
        self._layer_slider = self._am_panel.layer_slider
        self._layer_info_label = self._am_panel.layer_info_label
        self._layer_area_label = self._am_panel.layer_area_label
        self._min_wall_spin = self._am_panel.min_wall_spin
        self._wall_progress_label = self._am_panel.wall_progress_label
        self._mesh_result_edit = self._am_panel.mesh_result_edit
        self._mode_radio = self._am_panel.modeRadioButtons

        self.setAcceptDrops(True)

    # ----------------------------------------------------------------------
    # VTK initialization (delegated to viewport)
    # ----------------------------------------------------------------------
    def _init_vtk(self) -> None:
        try:
            self._viewport.initialize()
            self._renderer = self._viewport.renderer
            self._ori_marker = self._viewport._ori_marker
            self._cube_axes = self._viewport._cube_axes
            # Ensure internal state syncs
            self._grid_visible = False
        except Exception:
            logger.exception("VTK initialisation failed")
            self._set_status("VTK initialisation failed -- see log")

    # ----------------------------------------------------------------------
    # Status and snapshot helpers (unchanged logic)
    # ----------------------------------------------------------------------
    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)
        logger.debug("status: %s", message)

    def _snapshot(self, action: str) -> dict:
        snap: dict = {
            "action": action,
            "file": self._current_file,
            "background": tuple(self._viewport.get_background()) if self._viewport else (),
            "wireframe": self._wire_btn.isChecked(),
            "grid": self._grid_visible,
            "am_mode": self._am_mode.value,
            "build_dir": self._build_dir,
        }
        if self._actor is not None:
            snap["actor_props"] = _capture_actor_props(self._actor)
        return snap

    def _restore_snapshot(self, snap: dict) -> None:
        if snap["file"]:
            self.load_model(snap["file"], add_undo=False)
        else:
            self._clear_actor()

        if "background" in snap:
            self._viewport.set_background(*snap["background"])

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
        self._viewport.render()

    def _push_undo(self, action: str) -> None:
        self._undo_manager.push(self._snapshot(action))

    # ----------------------------------------------------------------------
    # Undo / Redo (delegates to manager)
    # ----------------------------------------------------------------------
    def undo(self) -> None:
        current = self._snapshot("undo")
        snap = self._undo_manager.undo(current)
        if snap is None:
            self._set_status("Nothing to undo.")
            return
        self._restore_snapshot(snap)
        self._set_status("Undone.")

    def redo(self) -> None:
        current = self._snapshot("redo")
        snap = self._undo_manager.redo(current)
        if snap is None:
            self._set_status("Nothing to redo.")
            return
        self._restore_snapshot(snap)
        self._set_status("Redone.")

    # ----------------------------------------------------------------------
    # Drag & drop (unchanged)
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # File I/O
    # ----------------------------------------------------------------------
    _READERS: Dict[str, type] = {
        ".stl": vtkSTLReader,
        ".ply": vtkPLYReader,
        ".obj": vtkOBJReader,
        ".vtp": vtkXMLPolyDataReader,
        ".vtk": vtkPolyDataReader,
    }

    @classmethod
    def _reader_for(cls, path: str):
        ext = Path(path).suffix.lower()
        reader_cls = cls._READERS.get(ext, vtkXMLPolyDataReader)
        reader = reader_cls()
        reader.SetFileName(str(path))
        return reader

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open 3-D Model", os.getcwd(),
            "3-D Models (*.stl *.obj *.ply *.vtp *.vtk);;All Files (*.*)",
        )
        if path:
            self.load_model(path)

    def load_model(self, path: str, *, add_undo: bool = True) -> bool:
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
        actor.GetProperty().SetColor(*_NAMED_COLORS.GetColor3d("LightSteelBlue"))
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

        self._wire_btn.setChecked(False)
        self._grid_btn.setChecked(self._grid_visible)
        self._mesh_result_edit.setPlainText("-")
        self._layer_info_label.setText("Layer: - / -")
        self._layer_area_label.setText("Area: -")

        self._viewport.reset_camera()
        self.model_loaded.emit(path)
        return True

    def _clear_actor(self) -> None:
        if self._actor is not None:
            self._viewport.remove_actor(self._actor)
            self._actor = None
            self._mapper = None
            self._plain_mapper = None
            self._source_poly = None
            self._current_file = None
            self.show_grid(False)
            self._viewport.render()

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

    def _toggle_wireframe(self, checked: bool) -> None:
        if self._actor is None:
            self._wire_btn.setChecked(False)
            return
        if checked:
            self._actor.GetProperty().SetRepresentationToWireframe()
            self._wire_btn.setIcon(QIcon(colorize_pixmap(
                QPixmap("line-icons:box-3-line.svg"),
                self.palette().highlightedText().color())))
        else:
            self._actor.GetProperty().SetRepresentationToSurface()
            self._wire_btn.setIcon(QIcon(colorize_pixmap(
                QPixmap("line-icons:global-line.svg"),
                self.palette().highlightedText().color())))
        self._viewport.render()

    def _choose_background(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if not color.isValid():
            return
        self._viewport.set_background(
            color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0)

    def _screenshot(self) -> None:
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
        self._grid_visible = visible
        self._viewport.show_grid(visible)
        self._grid_btn.setChecked(visible)

    def toggle_grid(self) -> None:
        self.show_grid(not self._grid_visible)

    # ----------------------------------------------------------------------
    # Export (unchanged logic, but uses _viewport)
    # ----------------------------------------------------------------------
    _FILTER_EXT: Dict[str, str] = {
        "*.stl": ".stl", "*.obj": ".obj", "*.ply": ".ply", "*.vtk": ".vtk",
    }

    def _show_export_dialog(self) -> None:
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

    # ----------------------------------------------------------------------
    # Analysis mode management (unchanged, but uses viewport)
    # ----------------------------------------------------------------------
    def _set_build_dir(self, vec: Tuple[float, float, float]) -> None:
        self._build_dir = vec
        self._refresh_analysis_if(self._am_mode)
        self._set_status(f"Build direction: {vec}")

    def _refresh_analysis_if(self, mode: AnalysisMode) -> None:
        if self._am_mode == mode:
            self._set_analysis_mode(mode)

    def _set_analysis_mode(self, mode: AnalysisMode) -> None:
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

        self._viewport.render()

    def _clear_am_overlays(self) -> None:
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
        prop.SetColor(*_NAMED_COLORS.GetColor3d("LightSteelBlue"))
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
        # Pass a callback that triggers the viewport’s render
        LightingDialog(
            self._actor,
            render_callback=self._viewport.render,
            parent=self,
        ).exec()

    def _show_statistics_dialog(self) -> None:
        """Open the model statistics dialog."""
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

    # ----------------------------------------------------------------------
    # Mesh check (unchanged except using viewport for rendering)
    # ----------------------------------------------------------------------
    def _run_mesh_check(self) -> None:
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

        lines += ["", "Overall: PASS" if not issues else "Overall: ISSUES FOUND"]
        self._mesh_result_edit.setPlainText("\n".join(lines))

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
            self._viewport.render()

        n_issues = int(n_boundary > 0) + int(n_nm > 0)
        self._set_status(
            "Mesh check: PASS" if not issues
            else f"Mesh check: {n_issues} issue(s) found"
        )

    # ----------------------------------------------------------------------
    # Overhang analysis (unchanged, but uses viewport)
    # ----------------------------------------------------------------------
    def _run_overhang_analysis(self) -> None:
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
        self._viewport.render()

        n_critical = int(np.sum(angles > threshold))
        pct = 100 * n_critical / max(len(angles), 1)
        self._set_status(
            f"Overhang: {n_critical} critical cells ({pct:.1f}%) -- "
            f"threshold {self._overhang_spin.value():.0f} deg from horizontal"
        )

    # ----------------------------------------------------------------------
    # Wall thickness (unchanged, but uses viewport)
    # ----------------------------------------------------------------------
    def _start_wall_thickness(self) -> None:
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
        if self._wall_worker is not None and self._wall_worker.isRunning():
            self._wall_worker.cancel()
            self._wall_worker.wait()
        self._wall_worker = None
        self._wall_progress_label.setText("")

    def _on_wall_thickness_result(self, thicknesses: np.ndarray) -> None:
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
        self._viewport.render()

        min_wall = self._min_wall_spin.value()
        n_thin = int(np.sum(thicknesses < min_wall))
        pct = 100 * n_thin / max(len(thicknesses), 1)
        self._set_status(
            f"Wall thickness: {n_thin} thin points ({pct:.1f}%) "
            f"below {min_wall:.2f} mm target  |  "
            f"range {min_t:.2f}-{max_t:.2f} mm"
        )

    def _on_wall_thickness_error(self, msg: str) -> None:
        self._wall_progress_label.setText("")
        self._set_status(f"Wall thickness error: {msg}")

    # ----------------------------------------------------------------------
    # Layer preview (unchanged)
    # ----------------------------------------------------------------------
    def _setup_layer_preview(self) -> None:
        if self._source_poly is None:
            return
        self._actor.GetProperty().SetOpacity(0.22)
        self._rebuild_layer_slider()
        self._update_layer_preview(self._layer_slider.value())

    def _rebuild_layer_slider(self) -> None:
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
        if self._am_mode != AnalysisMode.LAYER or self._source_poly is None:
            return

        for actor in self._am_overlays:
            self._viewport.remove_actor(actor)
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
        self._viewport.add_actor(section_actor)

        area = 0.0
        try:
            for i in range(filled_pd.GetNumberOfCells()):
                cell = filled_pd.GetCell(i)
                if cell.GetNumberOfPoints() == 3:
                    p0 = np.array(filled_pd.GetPoint(cell.GetPointId(0)))
                    p1 = np.array(filled_pd.GetPoint(cell.GetPointId(1)))
                    p2 = np.array(filled_pd.GetPoint(cell.GetPointId(2)))
                    area += 0.5 * float(np.linalg.norm(np.cross(p1 - p0, p2 - p0)))
        except Exception:
            logger.warning("Layer preview: could not compute cross-section area")

        self._layer_info_label.setText(f"Layer: {layer_idx + 1} / {n_layers}")
        self._layer_area_label.setText(f"Area: {area:.2f} mm\u00B2")
        self._viewport.render()
        self._set_status(
            f"Layer {layer_idx + 1}/{n_layers}  "
            f"h={layer_h:.3f} mm  area={area:.2f} mm\u00B2"
        )

    # ----------------------------------------------------------------------
    # Support estimate (unchanged)
    # ----------------------------------------------------------------------
    def _run_support_estimate(self) -> None:
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
        self._viewport.add_actor(oh_actor)

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

        self._viewport.render()
        self._set_status(
            f"Support: {int(np.sum(overhang_mask))} overhanging cells  |  "
            f"projected area {total_area:.1f} mm\u00B2  |  "
            f"estimated support vol ~{total_vol:.1f} mm\u00B3"
        )

    # ----------------------------------------------------------------------
    # Cleanup (unchanged but delegates to viewport)
    # ----------------------------------------------------------------------
    def cleanup(self) -> None:
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True
        logger.debug("ModelViewerWidget.cleanup() called")

        try:
            self._cancel_wall_worker()
        except Exception:
            logger.exception("cleanup: error cancelling wall worker")

        try:
            self._clear_am_overlays()
        except Exception:
            logger.exception("cleanup: error clearing AM overlays")

        if self._viewport:
            self._viewport.cleanup()

        self._actor = None
        self._mapper = None
        self._plain_mapper = None
        self._source_poly = None
        self._current_file = None

        self._viewport = None
        self._renderer = None
        self._ori_marker = None
        self._undo_manager.clear()

        logger.debug("ModelViewerWidget.cleanup() complete")

    def closeEvent(self, event) -> None:
        self.cleanup()
        event.accept()
