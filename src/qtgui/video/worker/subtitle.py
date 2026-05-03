import re
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum, auto, unique

from PyQt6.QtCore import QObject, pyqtSignal, QThread, pyqtSlot
import time

@dataclass
class SubtitleEntry:
    start_time: float  # Seconds
    end_time: float    # Seconds
    content: str

def parse_srt_time(time_str: str) -> float:
    """Converts 00:01:40,890 to seconds."""
    hours, minutes, seconds = time_str.replace(',', '.').split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

class SubtitleWorker(QObject):
    subtitle_changed = pyqtSignal(str)

    def __init__(self, srt_path: str, state_manager):
        super().__init__()
        self.srt_path = srt_path
        self.state_manager = state_manager
        self.subtitles: list[SubtitleEntry] = []
        self._last_index = -1
        self._load_srt()

    def _load_srt(self):
        """Parses SRT into structured SubtitleEntry objects."""
        try:
            with open(self.srt_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            # Regex to split SRT blocks
            blocks = re.split(r'\n\s*\n', content)
            for block in blocks:
                lines = block.splitlines()
                if len(lines) >= 3:
                    # Match timestamp line: 00:01:40,890 --> 00:01:41,760
                    times = re.findall(r'(\d+:\d+:\d+,\d+)', lines[1])
                    if len(times) == 2:
                        entry = SubtitleEntry(
                            start_time=parse_srt_time(times[0]),
                            end_time=parse_srt_time(times[1]),
                            content="\n".join(lines[2:])
                        )
                        self.subtitles.append(entry)
            # Ensure sorted for faster searching
            self.subtitles.sort(key=lambda x: x.start_time)
        except Exception as e:
            print(f"Error loading subtitles: {e}")

    @pyqtSlot()
    def run(self):
        """Main loop synced with state manager."""
        while self.state_manager.is_running():
            current_pos = self.state_manager.get_current_position()

            # Find the active subtitle
            active_text = ""
            for entry in self.subtitles:
                if entry.start_time <= current_pos <= entry.end_time:
                    active_text = entry.content
                    break
                elif entry.start_time > current_pos:
                    # Since list is sorted, we can stop early
                    break

            # Only emit if the subtitle content has changed
            # This prevents UI flickering
            if active_text != getattr(self, '_current_active_text', None):
                self._current_active_text = active_text
                self.subtitle_changed.emit(active_text)

            time.sleep(0.05)  # ~20Hz update rate is plenty for subtitles

