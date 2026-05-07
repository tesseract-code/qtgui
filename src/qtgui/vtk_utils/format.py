from PyQt6.QtGui import QSurfaceFormat


def _vtk_qt_default_format() -> QSurfaceFormat:
    # vtk versions differ: some provide a helper defaultformat on qt widgets, some do not.
    # this function tries vtk-provided defaults first, then falls back to a safe opengl format.
    try:
        from vtkmodules.qt.QVTKOpenGLNativeWidget import \
            QVTKOpenGLNativeWidget  # type: ignore
        if hasattr(QVTKOpenGLNativeWidget, "defaultFormat"):
            return QVTKOpenGLNativeWidget.defaultFormat()
    except Exception:
        pass

    try:
        from vtkmodules.qt.QVTKRenderWindowInteractor import \
            QVTKRenderWindowInteractor  # type: ignore
        if hasattr(QVTKRenderWindowInteractor, "defaultFormat"):
            return QVTKRenderWindowInteractor.defaultFormat()
    except Exception:
        pass

    fmt = QSurfaceFormat()
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    return fmt
