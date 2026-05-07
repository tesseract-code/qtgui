from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonDataModel import vtkPolyData
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkInteractionWidgets import vtkOrientationMarkerWidget
from vtkmodules.vtkRenderingAnnotation import vtkCubeAxesActor, vtkAxesActor
from vtkmodules.vtkRenderingCore import vtkRenderer, vtkActor

from qtgui.vtk_utils.render import OffscreenVTKWidget

class VTKViewport:
    """Encapsulates VTK rendering: renderer, camera, orientation marker, grid."""

    def __init__(self, vtk_widget: OffscreenVTKWidget):
        self._vtk_widget = vtk_widget
        self._renderer: vtkRenderer | None = None
        self._ori_marker: vtkOrientationMarkerWidget | None = None
        self._cube_axes: vtkCubeAxesActor | None = None
        self._grid_visible = False

    def initialize(self) -> None:
        ren = vtkRenderer()
        self._vtk_widget.GetRenderWindow().AddRenderer(ren)
        ren.SetBackground(vtkNamedColors().GetColor3d("SlateGray"))
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

    def get_background(self) -> tuple[float, float, float]:
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