"""
demo_cpu_widget.py
──────────────────
Standalone demo for CpuUtilizationWidget using real CPU statistics.

Requires:
    pip install psutil

Run with:
    python demo_cpu_widget.py
"""

import sys

import psutil
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QStatusBar

from qtgui.cpu_utilization import CpuUtilizationWidget


class DemoWindow(QMainWindow):

    SAMPLE_INTERVAL_MS = 1_000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CpuUtilizationWidget – live demo")
        self.resize(900, 480)

        self._cpu_widget = CpuUtilizationWidget()
        self.setCentralWidget(self._cpu_widget)

        self._status = QStatusBar()
        self.setStatusBar(self._status)

        # Prime psutil so the first real call returns a valid delta
        psutil.cpu_times_percent(interval=None, percpu=False)

        self._timer = QTimer(self)
        self._timer.setInterval(self.SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self._sample)
        self._timer.start()

    def _sample(self) -> None:
        ct = psutil.cpu_times_percent(interval=None, percpu=False)

        for stat, value in (
            ("user",   ct.user),
            ("system", ct.system),
            ("idle",   ct.idle),
            ("iowait", getattr(ct, "iowait", 0.0)),  # not present on macOS/Windows
        ):
            self._cpu_widget.update_cpu_stat(stat, value)

        self._status.showMessage(
            f"user={ct.user:.1f}%  "
            f"system={ct.system:.1f}%  "
            f"iowait={getattr(ct, 'iowait', 0.0):.1f}%  "
            f"idle={ct.idle:.1f}%"
        )


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("CpuUtilizationWidget Demo")
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()