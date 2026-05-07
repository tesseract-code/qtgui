import logging
from typing import Optional

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
from vtkmodules.vtkRenderingCore import vtkActor


logger = logging.getLogger(__name__)


class StatisticsDialog(QDialog):
    """Read-only dialog displaying geometry and material statistics."""

    def __init__(self, actor, parent=None) -> None:
        """Initialise the statistics dialog.

        Parameters
        ----------
        actor : vtkActor or None
            The actor for which statistics are displayed, or None if no model loaded.
        parent : QWidget, optional
            Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Model Statistics")
        self.setMinimumSize(420, 360)

        layout = QVBoxLayout(self)
        text_area = QTextEdit(readOnly=True)
        text_area.setText(self._build_report(actor))
        layout.addWidget(text_area)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    @staticmethod
    def _build_report(actor: Optional[vtkActor]) -> str:
        """Generate a textual report from an actor.

        Parameters
        ----------
        actor : vtkActor or None
            The actor to inspect.

        Returns
        -------
        str
            Formatted report string.
        """
        if actor is None:
            return "No model loaded."

        lines = ["=== Model Statistics ===", ""]

        try:
            b = actor.GetBounds()
            lines += [
                "Bounds:",
                f"  X : {b[0]:.4f}  to  {b[1]:.4f}",
                f"  Y : {b[2]:.4f}  to  {b[3]:.4f}",
                f"  Z : {b[4]:.4f}  to  {b[5]:.4f}",
                "",
                "Dimensions:",
                f"  X : {b[1] - b[0]:.4f}",
                f"  Y : {b[3] - b[2]:.4f}",
                f"  Z : {b[5] - b[4]:.4f}",
                "",
            ]
        except Exception as exc:
            lines += [f"[Bounds unavailable: {exc}]", ""]

        mapper = actor.GetMapper()
        if mapper is not None:
            try:
                data = mapper.GetInput()
                if data is None:
                    raise RuntimeError("mapper.GetInput() returned None")
                lines += [
                    "Geometry:",
                    f"  Points   : {data.GetNumberOfPoints()}",
                    f"  Polygons : {data.GetNumberOfCells()}",
                    "",
                ]
            except Exception as exc:
                logger.warning("Statistics: could not read geometry -- %s", exc)
                lines += [f"[Geometry unavailable: {exc}]", ""]

        try:
            prop = actor.GetProperty()
            lines += [
                "Material:",
                f"  Ambient  : {prop.GetAmbient():.2f}",
                f"  Diffuse  : {prop.GetDiffuse():.2f}",
                f"  Specular : {prop.GetSpecular():.2f}",
            ]
        except Exception as exc:
            logger.warning("Statistics: could not read material -- %s", exc)
            lines.append(f"[Material unavailable: {exc}]")

        return "\n".join(lines)
