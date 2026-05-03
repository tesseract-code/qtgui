from PyQt6 import QtWidgets, QtCore
from PyQt6.QtCore import QTimer

from qtgui.gauge import AnalogGauge, ColorZone


class GaugeDemoWindow(QtWidgets.QMainWindow):
    """Demo window to test gauge functionality."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fixed Gauge Widget Demo - Qt Coordinate System")
        self.setMinimumSize(1200, 800)

        # Central widget
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QtWidgets.QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)

        # Create test gauges
        self._create_test_gauges(main_layout)

        # Control panel
        self._create_control_panel(main_layout)

        # Apply styling
        self._apply_styling()

        # Demo timer
        self._setup_demo()

    def _create_test_gauges(self, main_layout: QtWidgets.QHBoxLayout) -> None:
        """Create test gauges with different orientations."""
        gauge_container = QtWidgets.QWidget()
        gauge_layout = QtWidgets.QGridLayout(gauge_container)
        gauge_layout.setSpacing(25)

        # Test 1: Temperature (Semicircle Top) - Should show min on left, max on right
        self.temp_gauge = AnalogGauge()
        self.temp_gauge.set_range(-20, 50)
        # self.temp_gauge.orientation = GaugeOrientation.SEMICIRCLE_TOP
        # self.temp_gauge.style = GaugeStyle.MODERN
        self.temp_gauge.set_display_options(units="°C", precision=1)
        self.temp_gauge.add_color_zone(-20, 0, "#3498DB", "Cold")
        self.temp_gauge.add_color_zone(0, 25, "#2ECC71", "Normal")
        self.temp_gauge.add_color_zone(25, 50, "#E74C3C", "Hot")
        self.temp_gauge.value = 22

        temp_container = self._create_labeled_gauge("Temperature (Semicircle)",
                                                    self.temp_gauge)
        gauge_layout.addWidget(temp_container, 0, 0)

        # Test 2: Speed (Full Circle)
        self.speed_gauge = AnalogGauge()
        self.speed_gauge.set_range(0, 160)
        # self.speed_gauge.orientation = GaugeOrientation.CIRCULAR
        # self.speed_gauge.style = GaugeStyle.NEON
        self.speed_gauge.set_display_options(units="km/h", precision=0)
        self.speed_gauge.add_color_zone(0, 60, "#00FF41", "Safe")
        self.speed_gauge.add_color_zone(60, 120, "#FF8000", "Caution")
        self.speed_gauge.add_color_zone(120, 160, "#FF0040", "Danger")
        # self.speed_gauge.set_glow_enabled(True)
        self.speed_gauge.value = 85

        speed_container = self._create_labeled_gauge("Speed (Full Circle)",
                                                     self.speed_gauge)
        gauge_layout.addWidget(speed_container, 0, 1)

        # Test 3: Battery (Quarter)
        self.battery_gauge = AnalogGauge()
        self.battery_gauge.set_range(0, 100)
        # self.battery_gauge.orientation = GaugeOrientation.QUARTER_TOP_RIGHT
        # self.battery_gauge.style = GaugeStyle.MINIMAL
        self.battery_gauge.set_display_options(units="%", precision=0)
        self.battery_gauge.add_color_zone(0, 20, "#E74C3C", "Critical")
        self.battery_gauge.add_color_zone(20, 60, "#F39C12", "Low")
        self.battery_gauge.add_color_zone(60, 100, "#2ECC71", "Good")
        self.battery_gauge.value = 75

        battery_container = self._create_labeled_gauge("Battery (Quarter)",
                                                       self.battery_gauge)
        gauge_layout.addWidget(battery_container, 1, 0)

        # Test 4: Pressure (Classic)
        self.pressure_gauge = AnalogGauge()
        self.pressure_gauge.set_range(0, 10)
        # self.pressure_gauge.orientation = GaugeOrientation.CIRCULAR
        # self.pressure_gauge.style = GaugeStyle.CLASSIC
        self.pressure_gauge.set_display_options(units="bar", precision=1)
        self.pressure_gauge.add_color_zone(0, 3, "#3498DB", "Low")
        self.pressure_gauge.add_color_zone(3, 7, "#2ECC71", "Normal")
        self.pressure_gauge.add_color_zone(7, 10, "#E74C3C", "High")
        self.pressure_gauge.value = 5.5

        pressure_container = self._create_labeled_gauge("Pressure (Classic)",
                                                        self.pressure_gauge)
        gauge_layout.addWidget(pressure_container, 1, 1)

        main_layout.addWidget(gauge_container, 4)  # 80% of space

        # Store all gauges
        self.all_gauges = [self.temp_gauge, self.speed_gauge,
                           self.battery_gauge, self.pressure_gauge]

    def _create_labeled_gauge(self, title: str, gauge: AnalogGauge) -> (
            QtWidgets.QWidget):
        """Create a labeled gauge container."""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Title
        title_label = QtWidgets.QLabel(f"<b>{title}</b>")
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                color: #2C3E50;
                font-size: 12pt;
                font-weight: bold;
                margin-bottom: 5px;
            }
        """)
        layout.addWidget(title_label)

        # Gauge
        layout.addWidget(gauge)

        # Info label
        info_label = QtWidgets.QLabel(
            f"Range: {gauge._min_value} to {gauge._max_value}")
        info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet("color: #7F8C8D; font-size: 9pt;")
        layout.addWidget(info_label)

        return container

    def _create_control_panel(self, main_layout: QtWidgets.QHBoxLayout) -> None:
        """Create control panel for testing."""
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(250)
        panel.setStyleSheet("""
            QWidget {
                background-color: #34495E;
                border-radius: 10px;
                padding: 15px;
            }
            QLabel {
                color: #ECF0F1;
                font-weight: bold;
                font-size: 11pt;
                margin: 5px 0px;
            }
            QPushButton {
                background-color: #3498DB;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 10pt;
                margin: 3px;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
            QPushButton:pressed {
                background-color: #21618C;
            }
            QCheckBox {
                color: #ECF0F1;
                font-weight: bold;
                font-size: 10pt;
                spacing: 8px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background-color: #2C3E50;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background-color: #3498DB;
                border: none;
                width: 20px;
                margin: -6px 0;
                border-radius: 10px;
            }
            QSlider::handle:horizontal:hover {
                background-color: #2980B9;
            }
        """)

        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(12)

        # Title
        title = QtWidgets.QLabel("🎛️ Control Panel")
        title.setStyleSheet(
            "font-size: 14pt; color: #ECF0F1; margin-bottom: 10px;")
        layout.addWidget(title)

        # Random values
        random_btn = QtWidgets.QPushButton("🎲 Random Values")
        random_btn.clicked.connect(self._set_random_values)
        layout.addWidget(random_btn)

        # Test specific values
        test_btn = QtWidgets.QPushButton("🧪 Test Min/Max")
        test_btn.clicked.connect(self._test_min_max)
        layout.addWidget(test_btn)

        # Reset button
        reset_btn = QtWidgets.QPushButton("↻ Reset to Defaults")
        reset_btn.clicked.connect(self._reset_values)
        layout.addWidget(reset_btn)

        layout.addWidget(QtWidgets.QLabel("Settings"))

        # Animation toggle
        self.anim_check = QtWidgets.QCheckBox("Enable Animations")
        self.anim_check.setChecked(True)
        self.anim_check.toggled.connect(self._toggle_animations)
        layout.addWidget(self.anim_check)

        layout.addWidget(QtWidgets.QLabel("Auto Demo"))

        # Auto demo
        self.auto_check = QtWidgets.QCheckBox("Auto Update")
        self.auto_check.toggled.connect(self._toggle_auto_demo)
        layout.addWidget(self.auto_check)

        # Speed slider
        layout.addWidget(QtWidgets.QLabel("Update Speed"))
        self.speed_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.speed_slider.setRange(100, 2000)
        self.speed_slider.setValue(1000)
        self.speed_slider.valueChanged.connect(self._update_demo_speed)
        layout.addWidget(self.speed_slider)

        layout.addStretch()

        # Debug info
        self.debug_label = QtWidgets.QLabel("Debug: Ready")
        self.debug_label.setStyleSheet(
            "color: #95A5A6; font-size: 8pt; margin-top: 10px;")
        layout.addWidget(self.debug_label)

        main_layout.addWidget(panel, 1)  # 20% of space

    def _apply_styling(self) -> None:
        """Apply main window styling."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #ECF0F1;
            }
        """)

    def _setup_demo(self) -> None:
        """Setup demo timer and values."""
        self.demo_timer = QTimer()
        self.demo_timer.timeout.connect(self._demo_update)

        # Demo sequences
        self.demo_sequences = {
            'temp': [-15, -10, -5, 0, 10, 20, 30, 40, 45, 35, 25, 15, 5],
            'speed': [0, 20, 45, 75, 100, 130, 155, 120, 90, 60, 30, 10],
            'battery': [100, 85, 70, 55, 40, 25, 15, 8, 25, 50, 75, 90],
            'pressure': [0.5, 2.0, 4.5, 6.8, 8.2, 9.5, 7.5, 5.0, 3.2, 1.8]
        }
        self.demo_index = 0

        # Connect signals for debugging
        for i, gauge in enumerate(self.all_gauges):
            gauge.value_changed.connect(
                lambda v, idx=i: self._on_value_changed(idx, v))
            gauge.zone_entered.connect(
                lambda z, idx=i: self._on_zone_entered(idx, z))

    def _set_random_values(self) -> None:
        """Set random values for testing."""
        import random
        self.temp_gauge.value = random.uniform(-15, 45)
        self.speed_gauge.value = random.uniform(0, 150)
        self.battery_gauge.value = random.uniform(5, 100)
        self.pressure_gauge.value = random.uniform(0.5, 9.5)
        self.debug_label.setText("Debug: Random values set")

    def _test_min_max(self) -> None:
        """Test min/max values."""
        self.temp_gauge.value = self.temp_gauge._min_value
        self.speed_gauge.value = self.speed_gauge._max_value
        self.battery_gauge.value = self.battery_gauge._min_value
        self.pressure_gauge.value = self.pressure_gauge._max_value
        self.debug_label.setText("Debug: Testing min/max values")

    def _reset_values(self) -> None:
        """Reset to default values."""
        self.temp_gauge.value = 22
        self.speed_gauge.value = 85
        self.battery_gauge.value = 75
        self.pressure_gauge.value = 5.5
        self.debug_label.setText("Debug: Reset to defaults")

    def _toggle_animations(self, checked: bool) -> None:
        """Toggle animations."""
        for gauge in self.all_gauges:
            gauge.set_animation_enabled(checked)
        self.debug_label.setText(
            f"Debug: Animations {'enabled' if checked else 'disabled'}")

    def _toggle_glow(self, checked: bool) -> None:
        """Toggle glow effects."""
        self.speed_gauge.set_glow_enabled(checked)

    def _toggle_auto_demo(self, checked: bool) -> None:
        """Toggle auto demo."""
        if checked:
            self.demo_timer.start(self.speed_slider.value())
            self.debug_label.setText("Debug: Auto demo started")
        else:
            self.demo_timer.stop()
            self.debug_label.setText("Debug: Auto demo stopped")

    def _update_demo_speed(self, value: int) -> None:
        """Update demo speed."""
        if self.auto_check.isChecked():
            self.demo_timer.start(value)

    def _demo_update(self) -> None:
        """Update demo values."""
        sequences = self.demo_sequences

        temp_seq = sequences['temp']
        speed_seq = sequences['speed']
        battery_seq = sequences['battery']
        pressure_seq = sequences['pressure']

        self.temp_gauge.value = temp_seq[self.demo_index % len(temp_seq)]
        self.speed_gauge.value = speed_seq[self.demo_index % len(speed_seq)]
        self.battery_gauge.value = battery_seq[
            self.demo_index % len(battery_seq)]
        self.pressure_gauge.value = pressure_seq[
            self.demo_index % len(pressure_seq)]

        self.demo_index += 1
        self.debug_label.setText(f"Debug: Demo step {self.demo_index}")

    def _on_value_changed(self, gauge_idx: int, value: float) -> None:
        """Handle value change events."""
        gauge_names = ["Temp", "Speed", "Battery", "Pressure"]
        # print(f"{gauge_names[gauge_idx]}: {value:.1f}")

    def _on_zone_entered(self, gauge_idx: int, zone: ColorZone) -> None:
        """Handle zone enter events."""
        gauge_names = ["Temp", "Speed", "Battery", "Pressure"]
        print(f"{gauge_names[gauge_idx]} entered {zone.label} zone")


def gauge_demo():
    import sys
    # Run the application
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')

    # Set application properties
    app.setApplicationName("Gauge Widget Demo")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Production Widgets")

    window = GaugeDemoWindow()
    window.show()

    print("Gauge Demo Started")
    print("- Temperature: Semicircle (min left, max right)")
    print("- Speed: Full circle (standard gauge layout)")
    print("- Battery: Quarter circle")
    print("- Pressure: Classic circular")
    print("\nTest the controls to verify correct behavior!")

    return sys.exit(app.exec())


# Demo application with correct implementation testing
if __name__ == "__main__":
    gauge_demo()
