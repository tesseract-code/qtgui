from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QSlider, QLabel, QApplication, QWidget, QVBoxLayout

from qtgui.slider import RangeSlider

if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("Float Range Slider - QSlider Feature Parity")
    layout = QVBoxLayout(window)

    # Example 1: Basic slider with ticks below
    slider1 = RangeSlider(orientation=Qt.Orientation.Horizontal)
    slider1.setRange(0.0, 100.0)
    slider1.setValues(25.5, 75.3)
    slider1.setTickPosition(QSlider.TickPosition.TicksBelow)
    slider1.setTickInterval(11.0)  # Tick every 10 units

    value_label1 = QLabel(
        f"Range: {slider1.values()[0]:.2f} - {slider1.values()[1]:.2f}")
    value_label1.setStyleSheet("font-size: 14px; padding: 10px;")

    slider1.rangeChanged.connect(
        lambda low, high: value_label1.setText(
            f"Range: {low:.2f} - {high:.2f}")
    )

    layout.addWidget(QLabel("Ticks Below (tickInterval=10.0):"))
    layout.addWidget(slider1)
    layout.addWidget(value_label1)

    # Example 2: Ticks on both sides
    slider2 = RangeSlider()
    slider2.setRange(-10.0, 10.0)
    slider2.setValues(-3.7, 5.2)
    slider2.setTickPosition(QSlider.TickPosition.TicksBothSides)
    slider2.setTickCount(10)  # 10 intervals = 11 tick marks

    value_label2 = QLabel(
        f"Range: {slider2.values()[0]:.2f} - {slider2.values()[1]:.2f}")
    value_label2.setStyleSheet("font-size: 14px; padding: 10px;")

    slider2.rangeChanged.connect(
        lambda low, high: value_label2.setText(
            f"Range: {low:.2f} - {high:.2f}")
    )

    layout.addWidget(QLabel("\nTicks Both Sides (tickCount=10):"))
    layout.addWidget(slider2)
    layout.addWidget(value_label2)

    # Example 3: Ticks above
    slider3 = RangeSlider()
    slider3.setRange(0.0, 50.0)
    slider3.setValues(10.0, 40.0)
    slider3.setTickPosition(QSlider.TickPosition.TicksAbove)
    slider3.setTickInterval(5.0)
    slider3.setTracking(False)  # Only emit signal on release

    value_label3 = QLabel(
        f"Range: {slider3.values()[0]:.1f} - {slider3.values()[1]:.1f}")
    value_label3.setStyleSheet("font-size: 14px; padding: 10px;")

    slider3.rangeChanged.connect(
        lambda low, high: value_label3.setText(
            f"Range: {low:.1f} - {high:.1f}")
    )

    layout.addWidget(
        QLabel("\nTicks Above, No Tracking (emits on release):"))
    layout.addWidget(slider3)
    layout.addWidget(value_label3)

    layout.addStretch()

    window.resize(600, 600)
    window.show()

    sys.exit(app.exec())
