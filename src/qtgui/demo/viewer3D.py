# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------
import os
os.environ["VTK_RENDERER"] = "Software"
import logging
import sys

from PyQt6.QtWidgets import QMainWindow

from qtcore.app import Application
from qtgui.viewerVTK import ModelViewerWidget, configure_surface_format

logger = logging.getLogger(__name__)


class _MainWindow(QMainWindow):
    """Tiny test window for quick visual inspection."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3-D Model Viewer -- AM Edition")
        viewer = ModelViewerWidget(self)
        viewer.model_loaded.connect(lambda p: logger.info("Loaded: %s", p))
        viewer.model_cleared.connect(lambda: logger.info("Cleared"))
        self.setCentralWidget(viewer)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    configure_surface_format()
    app = Application(argv=sys.argv)
    win = _MainWindow()
    win.resize(1400, 900)
    win.show()
    sys.exit(app.exec())
