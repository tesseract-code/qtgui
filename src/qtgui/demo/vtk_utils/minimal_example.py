import sys
import os
# Optional: force pure software rendering – totally safe here
# os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage
import vtk

class OffscreenVTKWidget(QWidget):
    """VTK widget that renders off‑screen and displays via QLabel."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)

        # Label to hold the rendered image
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # VTK off‑screen pipeline
        self.render_window = vtk.vtkRenderWindow()
        self.render_window.OffScreenRenderingOn()          # never touches X11
        self.render_window.SetSize(400, 300)

        self.renderer = vtk.vtkRenderer()
        self.render_window.AddRenderer(self.renderer)

        self.interactor = vtk.vtkRenderWindowInteractor()
        self.interactor.SetRenderWindow(self.render_window)
        self.interactor.Initialize()

        # Image export
        self.w2i = vtk.vtkWindowToImageFilter()
        self.w2i.SetInput(self.render_window)
        self.w2i.SetScale(1)

        # Mouse tracking
        self.setMouseTracking(True)
        self._last_pos = None

        # Initial render
        self._update_image()

    def resizeEvent(self, event):
        self.image_label.resize(self.size())
        self._update_image()

    def _update_image(self):
        """Render VTK scene and set the QLabel pixmap."""
        self.render_window.Render()
        self.w2i.Modified()
        self.w2i.Update()
        image_data = self.w2i.GetOutput()

        width, height, _ = image_data.GetDimensions()
        ncomp = image_data.GetNumberOfScalarComponents()
        if ncomp == 3 or ncomp == 4:
            from vtkmodules.util.numpy_support import vtk_to_numpy
            arr = vtk_to_numpy(image_data.GetPointData().GetScalars())
            arr = arr.reshape(height, width, ncomp)
            if ncomp == 4:
                arr = arr[:, :, :3]          # drop alpha
            h, w, _ = arr.shape
            bytes_per_line = 3 * w
            qim = QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qim).scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(pixmap)

    # ---------------- Mouse / Keyboard events → VTK interactor ----------------
    def _event_position_xy(self, event):
        """Extract integer pixel coordinates from an event (works for both pos() and position())."""
        pos = event.position()  # PyQt6: QPointF
        return int(pos.x()), int(pos.y())

    def mousePressEvent(self, event):
        x, y = self._event_position_xy(event)
        self._last_pos = event.pos()
        self.interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        btn = event.button()
        if btn == Qt.MouseButton.LeftButton:
            self.interactor.LeftButtonPressEvent()
        elif btn == Qt.MouseButton.RightButton:
            self.interactor.RightButtonPressEvent()
        elif btn == Qt.MouseButton.MiddleButton:
            self.interactor.MiddleButtonPressEvent()
        self._update_image()

    def mouseReleaseEvent(self, event):
        x, y = self._event_position_xy(event)
        self._last_pos = event.pos()
        self.interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        btn = event.button()
        if btn == Qt.MouseButton.LeftButton:
            self.interactor.LeftButtonReleaseEvent()
        elif btn == Qt.MouseButton.RightButton:
            self.interactor.RightButtonReleaseEvent()
        elif btn == Qt.MouseButton.MiddleButton:
            self.interactor.MiddleButtonReleaseEvent()
        self._update_image()

    def mouseMoveEvent(self, event):
        if self._last_pos is None:
            return
        x, y = self._event_position_xy(event)
        self.interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        self.interactor.MouseMoveEvent()
        self._update_image()

    def wheelEvent(self, event):
        # FIX: QWheelEvent uses position(), not pos()
        pos = event.position()
        x, y = int(pos.x()), int(pos.y())
        self.interactor.SetEventInformationFlipY(x, y, 0, 0, chr(0), 0, None)
        if event.angleDelta().y() > 0:
            self.interactor.MouseWheelForwardEvent()
        else:
            self.interactor.MouseWheelBackwardEvent()
        self._update_image()

    def keyPressEvent(self, event):
        pos = event.position() if hasattr(event, 'position') else event.pos()  # safeguard
        x, y = int(pos.x()), int(pos.y())
        self.interactor.SetEventInformation(x, y, 0, 0, event.text(), 0, None)
        self.interactor.KeyPressEvent()
        self._update_image()

    def keyReleaseEvent(self, event):
        pos = event.position() if hasattr(event, 'position') else event.pos()
        x, y = int(pos.x()), int(pos.y())
        self.interactor.SetEventInformation(x, y, 0, 0, event.text(), 0, None)
        self.interactor.KeyReleaseEvent()
        self._update_image()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTK + PyQt6 (off‑screen, safe)")
        self.setGeometry(100, 100, 800, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.vtk_widget = OffscreenVTKWidget()
        layout.addWidget(self.vtk_widget)

        # Simple sphere
        sphere = vtk.vtkSphereSource()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        self.vtk_widget.renderer.AddActor(actor)
        self.vtk_widget.renderer.SetBackground(0.1, 0.2, 0.4)
        self.vtk_widget._update_image()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())