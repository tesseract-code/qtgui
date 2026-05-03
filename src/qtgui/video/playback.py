from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout

from qtgui.video.controller import VideoPlayerController
from qtgui.video.gui.stack import VideoPlayerStack


class VideoPlaybackWidget(QWidget):
    """
    Self-contained video player widget.

    The widget validates its inputs eagerly so failures surface at
    construction time rather than during playback.  Pass a custom
    ``overlay`` to inject an alternative overlay implementation for
    testing or subclassing.

    Satisfies the ``CleanupTab`` duck-type protocol: call ``cleanup()``
    before removing the widget from a ``DockRegion``.
    """

    def __init__(
            self,
            video_path: str | Path,
            subtitle_path: str | Path | None = None,
            overlay: VideoPlayerStack | None = None,
            *,
            parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)

        v_path = Path(video_path)
        if not v_path.exists():
            raise FileNotFoundError(f"Video file not found: {v_path}")
        if not v_path.is_file():
            raise IsADirectoryError(
                f"Video path is not a regular file: {v_path}")

        s_path: Path | None = None
        if subtitle_path is not None:
            s_path = Path(subtitle_path)
            if not s_path.exists():
                raise FileNotFoundError(
                    f"Subtitle file not found: {s_path}")  # fix 2 — was v_path
            if not s_path.is_file():
                raise IsADirectoryError(  # fix 2 — was v_path
                    f"Subtitle path is not a regular file: {s_path}"
                )

        resolved_overlay = overlay if overlay is not None else VideoPlayerStack()
        self.controller = VideoPlayerController(
            v_path,
            subtitle_path=s_path,
            overlay_widget=resolved_overlay,
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.overlay_widget())

    def start(self):
        self.controller.start()

    def stop(self):
        self.controller.stop()

    def overlay_widget(self) -> QWidget:
        """Return the overlay surface managed by the controller."""
        return self.controller.overlay

    def cleanup(self) -> None:
        """
        Release all resources held by the controller.

        Idempotent: safe to call more than once.
        """
        if self.controller is None:
            return
        self.controller.cleanup()
        self.controller = None
