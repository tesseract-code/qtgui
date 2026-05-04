import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
import vtk

from qtcore.vtk_utils import SafeVTKWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTK + PyQt6 (old widget, deferred setup)")
        self.setGeometry(100, 100, 800, 600)

        self._vtk_setup_complete = False  # guard to run only once

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create the VTK widget but don't configure it yet
        self.vtk_widget = SafeVTKWidget(central)
        layout.addWidget(self.vtk_widget)

    def showEvent(self, event):
        """Called each time the window is shown."""
        super().showEvent(event)
        if not self._vtk_setup_complete:
            self._setup_vtk()
            self._vtk_setup_complete = True

    def _setup_vtk(self):
        # Now the widget has a valid native window handle
        renderer = vtk.vtkRenderer()
        self.vtk_widget.GetRenderWindow().AddRenderer(renderer)

        # ----- OPTIONAL but highly recommended -----
        # Off-screen rendering avoids a separate X child window entirely,
        # preventing the BadWindow error for good.
        self.vtk_widget.GetRenderWindow().SetOffScreenRendering(True)
        # -------------------------------------------

        # Simple sphere pipeline
        sphere = vtk.vtkSphereSource()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        renderer.AddActor(actor)
        renderer.SetBackground(0.1, 0.2, 0.4)

        # Initialize interactor – no need for Start(), Qt drives it
        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()
        self.interactor.Initialize()

        # Force an initial render
        self.vtk_widget.GetRenderWindow().Render()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())