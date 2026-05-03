import time

from PyQt6.QtCharts import QAbstractAxis, QAbstractSeries, QChart
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from qtdisplay.chart.config import (PlotConfig, AxesConfig, SeriesConfig, AxesDisplaySettings,
                                    ChartDisplaySettings, SeriesDisplaySettings)
from qtdisplay.chart.controller.area import QAreaChartController
from qtdisplay.chart.controller.base import batch_update_series


class CpuUtilizationWidget(QWidget):

    # How long to wait before discarding an incomplete batch (ms and seconds)
    BATCH_TIMEOUT_MS = 500
    BATCH_TIMEOUT_S = BATCH_TIMEOUT_MS / 1000

    # Stats that must all arrive before a batch is considered complete
    _REQUIRED_STATS = frozenset({'user', 'system', 'idle', 'iowait'})

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.controller = QAreaChartController(PlotConfig(is_real_time=False,
                                                          max_points=60))

        axes_config = AxesConfig(
            axisX_type=QAbstractAxis.AxisType.AxisTypeDateTime,
            axisY_type=QAbstractAxis.AxisType.AxisTypeValue)

        self.controller.add_series(SeriesConfig(name="Idle %",
                                                series_type=QAbstractSeries.SeriesType.SeriesTypeArea,
                                                axes_config=axes_config))
        self.controller.add_series(SeriesConfig(name="IOWait %",
                                                series_type=QAbstractSeries.SeriesType.SeriesTypeArea,
                                                axes_config=axes_config))
        self.controller.add_series(SeriesConfig(name="User %",
                                                series_type=QAbstractSeries.SeriesType.SeriesTypeArea,
                                                axes_config=axes_config))
        self.controller.add_series(SeriesConfig(name="System %",
                                                series_type=QAbstractSeries.SeriesType.SeriesTypeArea,
                                                axes_config=axes_config))

        axisX_settings = AxesDisplaySettings(axis_title="Time",
                                             axis_unit="HH:MM:ss",
                                             axis_tick_count=3)

        axisY_settings = AxesDisplaySettings(axis_title="Load",
                                             axis_unit="%",
                                             axis_tick_count=3)

        chart_settings = ChartDisplaySettings(title="CPU Load",
                                              theme=QChart.ChartTheme.ChartThemeLight)
        self.controller.set_chart_display_settings(chart_settings)
        self.controller.set_series_display_settings(
            "User %", SeriesDisplaySettings(color="#00A7E1"))
        self.controller.set_series_display_settings(
            "System %", SeriesDisplaySettings(color="red"))
        self.controller.set_series_display_settings(
            "IOWait %", SeriesDisplaySettings(color="orange"))
        self.controller.set_series_display_settings(
            "Idle %", SeriesDisplaySettings(color="lightGray"))

        self.controller.set_axis_display_settings(
            Qt.AlignmentFlag.AlignBottom, axisX_settings)
        self.controller.set_axis_display_settings(
            Qt.AlignmentFlag.AlignLeft, axisY_settings)

        layout.addWidget(self.controller.plot)

        # Batch state
        self._current_batch: dict[str, float] = {}
        self._batch_start_time: float | None = None

        # Timer-based cleanup for stale incomplete batches
        self._stale_batch_timer = QTimer(self)
        self._stale_batch_timer.setSingleShot(True)
        self._stale_batch_timer.setInterval(self.BATCH_TIMEOUT_MS)
        self._stale_batch_timer.timeout.connect(self._discard_stale_batch)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_cpu_stat(self, stat_name: str, value: float) -> None:
        """
        Receive one CPU statistic and update the chart when all four
        stats for the current interval have arrived.

        Args:
            stat_name: One of 'user', 'system', 'idle', 'iowait'
            value: Percentage as a float (0–100)
        """
        if stat_name not in self._REQUIRED_STATS:
            return

        if not self._current_batch:
            # First stat of a new batch — record when it started
            self._batch_start_time = time.time()
            self._stale_batch_timer.start()

        self._current_batch[stat_name] = float(value)

        if self._current_batch.keys() == self._REQUIRED_STATS:
            self._stale_batch_timer.stop()
            self._flush_batch()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _discard_stale_batch(self) -> None:
        """Called by the QTimer when a batch has not completed in time."""
        self._current_batch.clear()
        self._batch_start_time = None

    def _flush_batch(self) -> None:
        """Render the completed batch and reset state."""
        # Use the timestamp recorded when the batch *started* arriving so
        # the x-axis position reflects when the sample was taken, not when
        # rendering happens.
        timestamp = self._batch_start_time

        user_pct = self._current_batch['user']
        system_pct = self._current_batch['system']
        iowait_pct = self._current_batch['iowait']

        # Derive idle explicitly so the stacked areas always sum to 100 %,
        # regardless of rounding or discrepancies in the reported idle value.
        idle_pct = max(0.0, 100.0 - user_pct - system_pct - iowait_pct)

        # Stacked lower/upper bounds (bottom → top): system, user, iowait, idle
        system_top  = system_pct
        user_top    = system_top + user_pct
        iowait_top  = user_top + iowait_pct
        idle_top    = iowait_top + idle_pct  # == 100 by construction

        with batch_update_series(
            ["User %", "System %", "IOWait %", "Idle %"],
            self.controller,
            ignore_missing=False,
        ):
            self.controller.append_point("System %",  timestamp, system_top,  0)
            self.controller.append_point("User %",    timestamp, user_top,    system_top)
            self.controller.append_point("IOWait %",  timestamp, iowait_top,  user_top)
            self.controller.append_point("Idle %",    timestamp, idle_top,    iowait_top)

        self._current_batch.clear()
        self._batch_start_time = None