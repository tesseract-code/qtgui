# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------
import os

from PyQt6.QtGui import QSurfaceFormat

from image.gl.utils import get_surface_format
from qtgui.vtk_utils.format import _vtk_qt_default_format

os.environ["VTK_RENDERER"] = "Software"
import logging
import sys

from PyQt6.QtWidgets import QMainWindow

from qtcore.app import Application
from qtgui.vtk_utils.viewer3D import ModelViewerWidget

logger = logging.getLogger(__name__)


class _MainWindow(QMainWindow):
    """Tiny test window for quick visual inspection."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3-D Model Viewer -- AM Edition")
        self.viewer = ModelViewerWidget(self)
        self.viewer.model_loaded.connect(lambda p: logger.info("Loaded: %s", p))
        self.viewer.model_cleared.connect(lambda: logger.info("Cleared"))
        self.setCentralWidget(self.viewer)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    QSurfaceFormat.setDefaultFormat(get_surface_format())
    app = Application(argv=sys.argv)
    win = _MainWindow()
    # win.viewer._init_vtk()
    win.resize(1400, 900)
    win.show()

    sys.exit(app.exec())
