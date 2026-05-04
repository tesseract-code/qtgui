import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
import vtk

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VTK + PyQt6 Minimal Example")
        self.setGeometry(100, 100, 800, 600)

        # Central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # VTK widget
        self.vtk_widget = QVTKRenderWindowInteractor(central_widget)
        layout.addWidget(self.vtk_widget)

        # VTK pipeline
        renderer = vtk.vtkRenderer()
        self.vtk_widget.GetRenderWindow().AddRenderer(renderer)
        interactor = self.vtk_widget.GetRenderWindow().GetInteractor()

        # Simple sphere source
        sphere_source = vtk.vtkSphereSource()
        sphere_mapper = vtk.vtkPolyDataMapper()
        sphere_mapper.SetInputConnection(sphere_source.GetOutputPort())
        sphere_actor = vtk.vtkActor()
        sphere_actor.SetMapper(sphere_mapper)
        renderer.AddActor(sphere_actor)
        renderer.SetBackground(0.1, 0.2, 0.4)

        # Start the interactor
        interactor.Initialize()
        interactor.Start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())