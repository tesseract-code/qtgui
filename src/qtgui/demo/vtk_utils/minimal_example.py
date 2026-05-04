import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt6.QtCore import QTimer
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
import vtk

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTK + PyQt6 (deferred timer)")
        self.setGeometry(100, 100, 800, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Placeholder: we will create the VTK widget later
        self.vtk_widget = None

        # Schedule the setup once the event loop starts
        QTimer.singleShot(0, self.setup_vtk)

    def setup_vtk(self):
        # At this point the main window is shown and has a valid native handle
        self.vtk_widget = QVTKRenderWindowInteractor(self.centralWidget())
        self.centralWidget().layout().addWidget(self.vtk_widget)

        render_window = self.vtk_widget.GetRenderWindow()

        render_window.SetOffScreenRendering(True)

        renderer = vtk.vtkRenderer()
        render_window.AddRenderer(renderer)

        sphere = vtk.vtkSphereSource()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        renderer.AddActor(actor)
        renderer.SetBackground(0.1, 0.2, 0.4)

        interactor = render_window.GetInteractor()
        interactor.Initialize()
        render_window.Render()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())