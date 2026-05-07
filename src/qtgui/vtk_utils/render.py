import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QWidget, QLabel
from vtkmodules import all as vtk
from vtkmodules.util.numpy_support import vtk_to_numpy


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
        # Re-entrancy guard: vtkRenderWindow.Render() can pump the Qt event
        # loop, which may fire a repaint and call _update_image() again before
        # the first call returns, causing a RecursionError in vtk_to_numpy.
        self._rendering: bool = False

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

    def render(self):
        """Render and copy the current VTK frame into the QLabel."""
        self._update_image()

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
        if self._rendering:
            return  # prevent re-entrant calls triggered by Render() itself
        if not self._render_window.GetRenderers().GetNumberOfItems():
            return

        self._rendering = True
        try:
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
                    arr = arr[:, :, :3]

                arr = np.flipud(arr)
                arr = np.ascontiguousarray(arr)

                h, w, _ = arr.shape
                qim = QImage(bytes(arr.data), w, h, 3 * w, QImage.Format.Format_RGB888)
                self._image_label.resize(self.size())
                self._image_label.setPixmap(QPixmap.fromImage(qim))
        finally:
            self._rendering = False

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