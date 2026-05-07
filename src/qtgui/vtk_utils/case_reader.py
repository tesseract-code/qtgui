"""
EnSight Gold .case file reader helper.

Public API
----------
CaseFileReader
    Thin wrapper around ``vtkGenericEnSightReader`` that normalises the
    multiblock output into a single ``vtkPolyData`` surface suitable for
    direct consumption by ``ModelViewerWidget``.

Typical usage
-------------
>>> reader = CaseFileReader("/data/simulation.case")
>>> print(reader.time_steps)       # [0.0, 0.1, 0.2, ...]
>>> print(reader.variable_names)   # ['pressure', 'velocity', ...]
>>> poly = reader.load(time_index=0)
"""

__all__ = ["CaseFileReader"]

import logging
from pathlib import Path
from typing import Optional

from vtkmodules.vtkCommonDataModel import (
    vtkCompositeDataSet,
    vtkDataSet,
    vtkPolyData,
)
from vtkmodules.vtkFiltersCore import vtkAppendPolyData
from vtkmodules.vtkFiltersGeometry import vtkDataSetSurfaceFilter
from vtkmodules.vtkIOEnSight import vtkGenericEnSightReader

logger = logging.getLogger(__name__)


class CaseFileReader:
    """
    Read an EnSight Gold ``.case`` file and produce a merged surface mesh.

    The class wraps ``vtkGenericEnSightReader``, which handles both ASCII
    and binary EnSight Gold formats automatically.  Multiblock output is
    flattened into a single ``vtkPolyData`` object so callers never need to
    walk the composite-dataset tree themselves.

    Parameters
    ----------
    path : str
        Path to a ``.case`` descriptor file.  May be absolute or relative.

    Raises
    ------
    FileNotFoundError
        If *path* does not point to an existing file.
    ValueError
        If *path* does not carry a ``.case`` extension.

    Notes
    -----
    The underlying VTK reader is created lazily on the first property access
    or :meth:`load` call, so constructing the object is always cheap.
    """

    def __init__(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Case file not found: {path}")
        if p.suffix.lower() != ".case":
            raise ValueError(
                f"Expected a .case file; got extension {p.suffix!r}."
            )

        self._path: str = str(p.resolve())
        self._reader: Optional[vtkGenericEnSightReader] = None
        self._n_blocks: int = 0

    # ------------------------------------------------------------------ #
    # Public properties                                                    #
    # ------------------------------------------------------------------ #

    @property
    def path(self) -> str:
        """Absolute path to the ``.case`` descriptor file."""
        return self._path

    @property
    def time_steps(self) -> list[float]:
        """
        Simulation time values available in the file.

        Returns an empty list when the file contains no transient data.
        """
        reader = self._ensure_reader()
        time_sets = reader.GetTimeSets()
        if time_sets is None or time_sets.GetNumberOfItems() == 0:
            return []
        ts = time_sets.GetItem(0)
        return [ts.GetValue(i) for i in range(ts.GetNumberOfTuples())]

    @property
    def variable_names(self) -> list[str]:
        """Names of all scalar and vector fields defined in the file."""
        reader = self._ensure_reader()
        return [
            reader.GetDescription(i)
            for i in range(reader.GetNumberOfVariables())
        ]

    @property
    def n_blocks(self) -> int:
        """
        Number of leaf geometry blocks present in the last loaded dataset.

        Zero until :meth:`load` has been called at least once.
        """
        return self._n_blocks

    # ------------------------------------------------------------------ #
    # Public methods                                                       #
    # ------------------------------------------------------------------ #

    def load(self, *, time_index: int = 0) -> vtkPolyData:
        """
        Load and return a merged surface mesh at the requested time step.

        All geometry blocks are extracted as surface polygons and merged
        into a single ``vtkPolyData`` object.  Unstructured and structured
        grids are converted automatically via ``vtkDataSetSurfaceFilter``.

        Parameters
        ----------
        time_index : int, optional
            Zero-based index into :attr:`time_steps`.  Ignored when the
            file contains no transient data.  Defaults to ``0``.

        Returns
        -------
        vtkPolyData
            Merged surface geometry at the requested time.

        Raises
        ------
        IndexError
            If *time_index* is out of range for the available time steps.
        RuntimeError
            If the underlying VTK reader fails to update successfully.
        """
        steps = self.time_steps
        if steps:
            if not (0 <= time_index < len(steps)):
                raise IndexError(
                    f"time_index {time_index} out of range "
                    f"(file has {len(steps)} step(s))."
                )
            self._reader.SetTimeValue(steps[time_index])

        try:
            self._reader.Update()
        except Exception as exc:
            raise RuntimeError(
                f"VTK EnSight reader failed for {self._path!r}: {exc}"
            ) from exc

        mb = self._reader.GetOutput()
        poly = self._flatten_to_polydata(mb)
        self._n_blocks = self._count_leaf_blocks(mb)
        return poly

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _ensure_reader(self) -> vtkGenericEnSightReader:
        """
        Return the cached VTK reader, creating and priming it on first call.

        The reader is updated once during construction so that metadata
        properties (time steps, variable names) are available before
        :meth:`load` is called.
        """
        if self._reader is None:
            r = vtkGenericEnSightReader()
            r.SetCaseFileName(self._path)
            r.ReadAllVariablesOn()
            r.UpdateInformation()
            self._reader = r
        return self._reader

    def _flatten_to_polydata(self, dataset) -> vtkPolyData:
        """
        Recursively extract and merge all surface geometry from *dataset*.

        Parameters
        ----------
        dataset : vtkDataObject
            Root VTK data object, typically a ``vtkMultiBlockDataSet``.

        Returns
        -------
        vtkPolyData
            Single merged surface containing all geometry blocks.
        """
        appender = vtkAppendPolyData()
        self._collect_blocks(dataset, appender)
        appender.Update()
        return appender.GetOutput()

    def _collect_blocks(
        self,
        node,
        appender: vtkAppendPolyData,
    ) -> None:
        """
        Walk *node* depth-first, feeding every leaf surface into *appender*.

        Composite datasets are traversed recursively.  Plain ``vtkPolyData``
        leaves are passed directly; all other ``vtkDataSet`` subtypes are
        first pushed through ``vtkDataSetSurfaceFilter`` to obtain a
        polygonal surface.

        Parameters
        ----------
        node : vtkDataObject
            Current node in the VTK composite-dataset tree.
        appender : vtkAppendPolyData
            Accumulator that collects all extracted surfaces.
        """
        if isinstance(node, vtkCompositeDataSet):
            it = node.NewIterator()
            it.InitTraversal()
            while not it.IsDoneWithTraversal():
                child = it.GetCurrentDataObject()
                if child is not None:
                    self._collect_blocks(child, appender)
                it.GoToNextItem()

        elif isinstance(node, vtkPolyData):
            appender.AddInputData(node)

        elif isinstance(node, vtkDataSet):
            surf = vtkDataSetSurfaceFilter()
            surf.SetInputData(node)
            surf.Update()
            appender.AddInputData(surf.GetOutput())

        else:
            logger.debug(
                "CaseFileReader: skipping unrecognised block type %s",
                type(node).__name__,
            )

    def _count_leaf_blocks(self, dataset) -> int:
        """
        Return the total number of non-empty leaf blocks in *dataset*.

        Parameters
        ----------
        dataset : vtkDataObject
            Root VTK data object.

        Returns
        -------
        int
            Count of non-``None`` leaf data objects in the composite tree.
        """
        if not isinstance(dataset, vtkCompositeDataSet):
            return 1

        count = 0
        it = dataset.NewIterator()
        it.InitTraversal()
        while not it.IsDoneWithTraversal():
            if it.GetCurrentDataObject() is not None:
                count += 1
            it.GoToNextItem()
        return count