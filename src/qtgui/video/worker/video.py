import json
import logging
import os
import subprocess
import time

import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from qtgui.video.worker.state import PlaybackStateManager

logger = logging.getLogger(__name__)


def get_video_rotation(video_path: str) -> int:
    """Extract rotation metadata"""
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_streams', '-select_streams', 'v:0',
        '-show_entries', 'stream_tags:stream_side_data',
        video_path
    ]

    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        result = subprocess.run(cmd, capture_output=True, text=True,
                                startupinfo=startupinfo)
        data = json.loads(result.stdout)

        if not data.get('streams'):
            return 0

        stream = data['streams'][0]
        tags = stream.get('tags', {})
        if 'rotate' in tags:
            return int(float(tags['rotate'])) % 360

        side_data_list = stream.get('side_data_list', [])
        for side_data in side_data_list:
            if 'rotation' in side_data:
                return int(float(side_data['rotation'])) % 360
    except Exception:
        pass

    return 0


def get_video_info(video_path: str) -> dict:
    """Extract video metadata"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {}
    info = {
        'fps': cap.get(cv2.CAP_PROP_FPS),
        'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        'duration_ms': (cap.get(cv2.CAP_PROP_FRAME_COUNT) /
                        cap.get(cv2.CAP_PROP_FPS)) * 1000,
        'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        'rotation': get_video_rotation(video_path)
    }
    cap.release()
    return info


# ==========================================
# VIDEO STREAM WORKER (IMPROVED)
# ==========================================

class VideoStreamWorker(QObject):
    """
    Improved video worker synchronized to shared state manager.
    Uses wall-clock as master clock for simpler synchronization.
    """

    frame_ready = pyqtSignal(np.ndarray)
    finished = pyqtSignal()
    position_changed = pyqtSignal(int)
    error_occurred = pyqtSignal(str)

    # Sync thresholds
    SYNC_THRESHOLD = 0.040  # 40ms
    NOSYNC_THRESHOLD = 1.0  # 1 second

    def __init__(self, video_path: str, state_manager: PlaybackStateManager):
        super().__init__()
        self.video_path = video_path
        self.state = state_manager

        # Metadata
        self.info = get_video_info(video_path)
        print(self.info)
        self.rotation = self.info.get('rotation', 0)
        self.fps = self.info.get('fps', 30.0)
        print("")
        self.frame_duration = 1.0 / self.fps

        # Seek tracking
        self._current_seek_gen = 0

        # Debug counters
        self._frame_count = 0
        self._skip_count = 0
        self._delay_count = 0

    def run(self):
        """Main video playback loop"""
        logger.info("Video worker starting")
        cap = cv2.VideoCapture(self.video_path)

        if not cap.isOpened():
            logger.error(f"Could not open video: {self.video_path}")
            self.error_occurred.emit(f"Could not open {self.video_path}")
            return

        logger.info(f"Video opened: {self.info}")

        try:
            loop_count = 0
            while self.state.is_running():
                # Get current state
                state = self.state.get_state()

                # Handle seek
                if state['seek_generation'] != self._current_seek_gen:
                    logger.info(
                        f"Video detected seek: gen {self._current_seek_gen} -> {state['seek_generation']}, pos={state['position']:.2f}s")
                    cap.set(cv2.CAP_PROP_POS_MSEC, state['position'] * 1000)
                    self._current_seek_gen = state['seek_generation']
                    logger.info(f"Video seeked to {state['position']:.2f}s")
                    continue

                # Handle pause
                if not state['playing']:
                    if loop_count % 20 == 0:
                        logger.debug("Video paused")
                    # time.sleep(0.05)
                    loop_count += 1
                    continue

                # Handle reverse playback
                if state['reverse']:
                    self._handle_reverse(cap)
                    continue

                # Normal forward playback - sync to wall clock
                target_position = state['position']  # Master clock position

                # Read next frame
                ret, frame = cap.read()
                if not ret:
                    logger.info("Video reached end")
                    self.state.stop_playback()
                    self.finished.emit()
                    break

                # Get frame timestamp
                frame_pos = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

                # Calculate sync difference
                diff = frame_pos - target_position

                if abs(diff) > self.NOSYNC_THRESHOLD:
                    # Way out of sync - seek to target
                    logger.warning(
                        f"Video out of sync: frame={frame_pos:.2f}s, target={target_position:.2f}s, diff={diff:.2f}s - SEEKING")
                    cap.set(cv2.CAP_PROP_POS_MSEC, target_position * 1000)
                    continue

                elif diff > self.SYNC_THRESHOLD:
                    # Frame ahead - delay display
                    delay = diff - (self.SYNC_THRESHOLD / 2)
                    self._delay_count += 1
                    if self._delay_count % 50 == 0:
                        logger.debug(
                            f"Video ahead by {diff * 1000:.1f}ms, delaying {delay * 1000:.1f}ms (count={self._delay_count})")
                    time.sleep(delay)

                elif diff < -self.SYNC_THRESHOLD:
                    # Frame behind - skip frame
                    self._skip_count += 1
                    if self._skip_count % 50 == 0:
                        logger.debug(
                            f"Video behind by {abs(diff) * 1000:.1f}ms, skipping frame (count={self._skip_count})")
                    continue

                # Display frame
                self._frame_count += 1
                frame = np.flipud(frame)
                self._emit_frame(frame)
                self.position_changed.emit(int(frame_pos * 1000))

                # Debug output every 2 seconds
                if self._frame_count % 60 == 0:
                    logger.debug(
                        f"Video stats: frames={self._frame_count}, skipped={self._skip_count}, delayed={self._delay_count}, pos={frame_pos:.2f}s")

                # Small sleep to prevent busy loop
                time.sleep(self.frame_duration * 0.05)

        except Exception as e:
            logger.error(f"Video worker error: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            cap.release()
            logger.info("Video worker exiting")

    def _handle_reverse(self, cap):
        """Handle reverse playback"""
        cur_pos = cap.get(cv2.CAP_PROP_POS_MSEC)
        new_pos = max(0, cur_pos - 40)
        cap.set(cv2.CAP_PROP_POS_MSEC, new_pos)

        ret, frame = cap.read()
        if ret:
            frame = np.flipud(frame)
            self._emit_frame(frame)
            self.position_changed.emit(int(new_pos))

        time.sleep(self.frame_duration)

        if new_pos == 0:
            logger.info("Reverse playback reached beginning")
            self.state.stop_playback()

    def _emit_frame(self, frame):
        """Apply rotation and emit"""
        if self.rotation == 0:
            self.frame_ready.emit(frame)
        elif self.rotation == 90:
            self.frame_ready.emit(cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE))
        elif self.rotation == 180:
            self.frame_ready.emit(cv2.rotate(frame, cv2.ROTATE_180))
        elif self.rotation == 270:
            self.frame_ready.emit(
                cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE))
