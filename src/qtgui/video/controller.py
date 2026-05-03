import logging
from pathlib import Path

from PyQt6.QtCore import (
    QThread, QDeadlineTimer
)

from qtgui.video.gui.stack import VideoPlayerStack
from qtgui.video.worker.audio import AudioStreamWorker
from qtgui.video.worker.state import PlaybackStateManager
from qtgui.video.worker.subtitle import SubtitleWorker
from qtgui.video.worker.video import VideoStreamWorker

logger = logging.getLogger(__name__)


class VideoPlayerController:
    """
    Controls video, audio, and subtitle playback via three independent
    worker threads that share a single ``PlaybackStateManager``.
    """

    def __init__(
        self,
        video_path: Path | str,
        overlay_widget: VideoPlayerStack,
        subtitle_path: Path | str | None = None,  # fix 0 — accept the param
    ) -> None:
        self.video_path: Path = Path(video_path)   # fix 5 — keep as Path
        self.overlay = overlay_widget

        # fix 6 — non-None at construction; only becomes None in cleanup()
        self.state_manager: PlaybackStateManager = PlaybackStateManager()

        self.video_worker:    VideoStreamWorker | None = None
        self.audio_worker:    AudioStreamWorker | None = None
        self.video_thread:    QThread | None = None
        self.audio_thread:    QThread | None = None

        self.subtitle_path:   Path | None = (Path(subtitle_path)
                                             if subtitle_path else None)
        self.subtitle_worker: SubtitleWorker | None = None
        self.subtitle_thread: QThread | None = None

        self._connect_overlay_signals()
        logger.info("Controller initialised for %s", self.video_path)

    # ── overlay wiring ────────────────────────────────────────────────────────

    def _connect_overlay_signals(self) -> None:
        self.overlay.play_pause_clicked.connect(self._on_play_pause)
        self.overlay.forward_clicked.connect(self._on_forward)
        self.overlay.backward_clicked.connect(self._on_backward)
        self.overlay.reverse_clicked.connect(self._on_reverse)
        self.overlay.seek_requested.connect(self._on_seek)
        self.overlay.volume_changed.connect(self._on_volume_changed)
        self.overlay.subtitle_changed.connect(self.set_subtitle_path)

    def _connect_worker_signals(self) -> None:
        self.video_worker.frame_ready.connect(self.overlay.set_frame)
        self.video_worker.position_changed.connect(self.overlay.set_position)
        self.video_worker.finished.connect(self._on_playback_finished)
        self.video_worker.error_occurred.connect(self._on_error)
        self.audio_worker.error_occurred.connect(self._on_error)
        self.audio_thread.started.connect(self.audio_worker.run)
        self.video_thread.started.connect(self.video_worker.run)

    def _create_workers(self) -> None:
        self.audio_worker = AudioStreamWorker(self.video_path, self.state_manager)
        self.video_worker = VideoStreamWorker(self.video_path, self.state_manager)
        self.audio_thread = QThread()
        self.video_thread = QThread()
        self.audio_worker.moveToThread(self.audio_thread)
        self.video_worker.moveToThread(self.video_thread)

    # ── playback lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start video playback. No-op if already running."""
        if self.video_worker is not None:
            logger.warning("start() called while already running")
            return

        logger.info("Starting playback")
        self._create_workers()
        self._connect_worker_signals()

        duration_ms = int(self.video_worker.info.get("duration_ms", 0))
        self.overlay.set_duration(duration_ms)
        logger.info("Video duration: %d ms", duration_ms)

        self.audio_thread.start()   # audio first for better A/V sync
        self.video_thread.start()

        if self.subtitle_path:
            self._start_subtitle_subsystem()

        self.state_manager.start_playback()
        self.overlay.set_playing_state(True)

    def stop(self) -> None:
        """
        Stop all three threads and clear their references.

        Uses a 5-second deadline per thread before escalating to
        ``terminate()``.  ``terminate()`` is a last resort — it may leave
        file handles or shared-memory segments in an inconsistent state;
        the log warning is intentional so operators can detect it.
        """
        logger.info("=== STOPPING PLAYBACK ===")
        self.state_manager.stop_playback()

        timeout = 5000

        # ---- Subtitle thread (stop first; it depends on state_manager) ----
        self._stop_subtitle_subsystem()   # fix 1 — was missing entirely

        # ---- Audio thread ----
        if self.audio_thread and self.audio_thread.isRunning():
            self.audio_thread.quit()
            if not self.audio_thread.wait(QDeadlineTimer(timeout)):
                logger.warning("Audio thread did not stop within %d ms — terminating", timeout)
                self.audio_thread.terminate()   # last resort; see docstring
            else:
                logger.info("Audio thread stopped")

        # ---- Video thread ----
        if self.video_thread and self.video_thread.isRunning():
            self.video_thread.quit()
            if not self.video_thread.wait(QDeadlineTimer(timeout)):
                logger.warning("Video thread did not stop within %d ms — terminating", timeout)
                self.video_thread.terminate()   # last resort; see docstring
            else:
                logger.info("Video thread stopped")

        self.video_worker = None
        self.audio_worker = None
        self.video_thread = None
        self.audio_thread = None

    def cleanup(self) -> None:
        """
        Release all resources held by this controller.

        Called by ``VideoPlayerWidget.cleanup()`` which satisfies the
        ``CleanupTab`` protocol used by ``DockTabBar``.
        """
        # fix 4 — corrected docstring (was "called automatically by thread.finished")
        self.stop()
        self.state_manager = None   # type: ignore[assignment]

    # ── subtitle subsystem ────────────────────────────────────────────────────

    def set_subtitle_path(self, path: Path | str) -> None:   # fix 7 — accept Path too
        """
        Load or swap subtitles at any time.

        Safe to call before ``start()`` (the path is stored and activated
        when playback begins) or during live playback (restarts the subtitle
        worker immediately).
        """
        self.subtitle_path = Path(path)

        if self.state_manager.is_running():
            self._start_subtitle_subsystem()

    def _start_subtitle_subsystem(self) -> None:
        if not self.subtitle_path:
            return

        self._stop_subtitle_subsystem()

        self.subtitle_worker = SubtitleWorker(self.subtitle_path, self.state_manager)
        self.subtitle_thread = QThread()
        self.subtitle_worker.moveToThread(self.subtitle_thread)

        self.subtitle_worker.subtitle_changed.connect(self.overlay.set_subtitle_text)
        self.subtitle_thread.started.connect(self.subtitle_worker.run)
        self.subtitle_thread.finished.connect(self.subtitle_thread.deleteLater)

        self.subtitle_thread.start()

    def _stop_subtitle_subsystem(self) -> None:
        """Tear down the subtitle thread and worker cleanly."""
        if self.subtitle_thread and self.subtitle_thread.isRunning():
            self.subtitle_thread.quit()
            self.subtitle_thread.wait()

        # fix 2 — clear references AFTER the thread has stopped, not before
        self.subtitle_worker = None
        self.subtitle_thread = None
        self.overlay.set_subtitle_text("")

    # ── overlay signal handlers ───────────────────────────────────────────────

    def _on_play_pause(self, should_play: bool) -> None:
        logger.info("play_pause: should_play=%s", should_play)
        if should_play:
            self.state_manager.resume()
        else:
            self.state_manager.pause()

    def _on_forward(self) -> None:
        if not self.video_worker:
            return
        duration_ms = int(self.video_worker.info.get("duration_ms", 0))
        current_pos = self.state_manager.get_current_position()
        new_pos = min(current_pos + 10.0, duration_ms / 1000.0)
        logger.info("Forward: %.2fs -> %.2fs", current_pos, new_pos)
        self.state_manager.seek(new_pos)

    def _on_backward(self) -> None:
        if not self.video_worker:
            return
        current_pos = self.state_manager.get_current_position()
        new_pos = max(current_pos - 10.0, 0.0)
        logger.info("Backward: %.2fs -> %.2fs", current_pos, new_pos)
        self.state_manager.seek(new_pos)

    def _on_reverse(self, enabled: bool) -> None:
        logger.info("Reverse: enabled=%s", enabled)
        self.state_manager.set_reverse(enabled)

    def _on_seek(self, position_ms: int) -> None:
        logger.info("Seek: %d ms (%.2fs)", position_ms, position_ms / 1000.0)
        self.state_manager.seek(position_ms / 1000.0)

    def _on_volume_changed(self, volume: float) -> None:
        if self.audio_worker is None:   # fix 3 — guard before start()/after stop()
            return
        self.audio_worker.set_volume(volume)

    def _on_playback_finished(self) -> None:
        logger.info("Playback finished")
        self.overlay.set_playing_state(False)

    def _on_error(self, error_msg: str) -> None:
        logger.error("Playback error: %s", error_msg)
