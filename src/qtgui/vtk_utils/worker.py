import math
import threading

import logging
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkPoints, vtkIdList
from vtkmodules.vtkCommonDataModel import vtkPolyData
from vtkmodules.vtkFiltersCore import vtkTriangleFilter, vtkPolyDataNormals
from vtkmodules.vtkFiltersGeneral import vtkOBBTree

logger = logging.getLogger(__name__)


class WallThicknessWorker(QThread):
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
