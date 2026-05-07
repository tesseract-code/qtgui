from typing import Dict

from PyQt6.QtWidgets import QDialog, QGridLayout, QDoubleSpinBox, QLabel, \
    QDialogButtonBox
from vtkmodules.vtkRenderingCore import vtkActor


class LightingDialog(QDialog):
    def __init__(self, actor: vtkActor, render_callback=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lighting Controls")
        self.setFixedSize(320, 185)
        self._actor = actor
        self._render = render_callback if render_callback else (lambda: None)

        layout = QGridLayout(self)
        specs = [
            ("Ambient", "ambient", actor.GetProperty().GetAmbient()),
            ("Diffuse", "diffuse", actor.GetProperty().GetDiffuse()),
            ("Specular", "specular", actor.GetProperty().GetSpecular()),
        ]
        self._spinboxes: Dict[str, QDoubleSpinBox] = {}
        for row, (label, key, current) in enumerate(specs):
            layout.addWidget(QLabel(f"{label}:"), row, 0)
            sb = QDoubleSpinBox()
            sb.setRange(0.0, 1.0)
            sb.setSingleStep(0.05)
            sb.setDecimals(2)
            sb.setValue(current)
            sb.valueChanged.connect(self._apply)
            layout.addWidget(sb, row, 1)
            self._spinboxes[key] = sb

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons, len(specs), 0, 1, 2)

    def _apply(self) -> None:
        prop = self._actor.GetProperty()
        prop.SetAmbient(self._spinboxes["ambient"].value())
        prop.SetDiffuse(self._spinboxes["diffuse"].value())
        prop.SetSpecular(self._spinboxes["specular"].value())
        self._render()  # uses the callback to update the off‑screen widget
