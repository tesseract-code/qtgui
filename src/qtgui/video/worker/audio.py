import array
import logging
import os
import queue
import subprocess
import threading
import time

import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal

from qtgui.video.worker.state import PlaybackStateManager

logger = logging.getLogger(__name__)


class AudioStreamWorker(QObject):
    """
    Audio worker with seek/pause synchronisation via PlaybackStateManager,
    and volume/mute control via the VolumeWidget signals.

    Wiring up the volume widget
    ---------------------------
        vol_widget.volume_changed.connect(worker.set_volume)
        vol_widget.mute_changed.connect(worker.set_muted)

    The worker never imports VolumeWidget directly — it only depends on the
    two plain signals, so it stays decoupled from the UI layer.
    """

    position_changed = pyqtSignal(float)
    finished         = pyqtSignal()
    error_occurred   = pyqtSignal(str)

    def __init__(self, video_path: str, state_manager: PlaybackStateManager):
        super().__init__()
        self.video_path = video_path
        self.state      = state_manager

        # Audio parameters
        self.sample_rate  = 44100
        self.channels     = 2
        self.sample_width = 2          # bytes — matches int16

        # Audio components
        self._stream         = None
        self._decode_process = None
        self._audio_queue    = queue.Queue(maxsize=100)

        # Seek tracking
        self._current_seek_gen  = 0
        self._decode_position   = 0.0

        # Volume / pause state read in the SD callback (C thread, no lock allowed).
        # _volume and _muted use plain assignment — atomic on CPython.
        # _is_playing_mirror is updated in the monitor loop and read in the
        # callback, avoiding the RLock acquisition that state.is_playing() would
        # require from a real-time C thread.
        self._volume: float           = 1.0   # 0.0 – 1.0
        self._muted:  bool            = False
        self._is_playing_mirror: bool = False

        # Signals the decode thread to pause reading during a seek so that
        # _start_decode_process can safely replace _decode_process.
        self._seeking = threading.Event()

        # Debug counters
        self._callback_count = 0
        self._silence_count  = 0

    # ------------------------------------------------------------------
    # Public volume API  (connect directly to VolumeWidget signals)
    # ------------------------------------------------------------------

    def set_volume(self, volume: float) -> None:
        """
        Set playback volume.  Accepts 0.0 (silent) – 1.0 (full).

        Connect to ``VolumeWidget.volume_changed``::

            vol_widget.volume_changed.connect(worker.set_volume)
        """
        self._volume = max(0.0, min(1.0, volume))
        logger.debug("Audio volume set to %.2f", self._volume)

    def set_muted(self, muted: bool) -> None:
        """
        Mute or unmute audio output.

        Connect to ``VolumeWidget.mute_changed``::

            vol_widget.mute_changed.connect(worker.set_muted)
        """
        self._muted = muted
        logger.debug("Audio muted=%s", muted)

    # ------------------------------------------------------------------
    # Worker entry point
    # ------------------------------------------------------------------

    def run(self):
        """
        Audio playback entry point.

        **Must be called on a dedicated worker thread** — this method blocks
        for the duration of playback.  Calling it on the Qt main thread will
        freeze the UI.
        """
        logger.info("Audio worker starting")
        try:
            decode_thread = threading.Thread(
                target=self._decode_audio, daemon=True
            )
            decode_thread.start()
            logger.info("Decode thread started")

            # RawOutputStream works with plain bytes in the callback — no NumPy
            # dependency.  blocksize matches the old frames_per_buffer value.
            self._stream = sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=1024,
                callback=self._audio_callback,
            )
            self._stream.start()
            logger.info("Audio stream started")

            loop_count = 0
            while self.state.is_running():
                state = self.state.get_state()

                # Mirror playing state for lock-free use in the SD callback.
                self._is_playing_mirror = state.playing

                if state.seek_generation != self._current_seek_gen:
                    logger.info(
                        "Audio monitor detected seek: gen %d -> %d, pos=%.2fs",
                        self._current_seek_gen, state.seek_generation, state.position,
                    )
                    self._handle_seek(state.position, state.seek_generation)
                    logger.info("Audio monitor seek handling complete")

                if loop_count % 20 == 0:
                    logger.debug(
                        "Audio monitor: playing=%s pos=%.2fs queue=%d "
                        "callbacks=%d silence=%d vol=%.2f muted=%s process_alive=%s",
                        state.playing, state.position,
                        self._audio_queue.qsize(),
                        self._callback_count, self._silence_count,
                        self._volume, self._muted,
                        self._decode_process and self._decode_process.poll() is None,
                    )

                # Throttle: emit position ~every 250 ms (5 × 50 ms sleep).
                if loop_count % 5 == 0:
                    self.position_changed.emit(state.position)

                loop_count += 1
                time.sleep(0.05)

        except Exception as e:
            logger.error("Audio worker error: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            logger.info("Audio worker cleaning up")
            self._cleanup()

    # ------------------------------------------------------------------
    # Decode thread
    # ------------------------------------------------------------------

    def _decode_audio(self):
        """Background thread: pipe ffmpeg PCM output into the audio queue."""
        logger.info("Audio decode thread starting")
        self._start_decode_process(0.0)

        chunks_decoded = 0
        last_seek_gen  = self._current_seek_gen

        while self.state.is_running():
            # Pause reading while the monitor thread replaces _decode_process.
            if self._seeking.is_set():
                time.sleep(0.01)
                continue

            state = self.state.get_state()
            if state.seek_generation != last_seek_gen:
                last_seek_gen = state.seek_generation

            # Capture a local reference so a concurrent _start_decode_process
            # reassignment cannot cause us to read from the wrong process.
            process = self._decode_process
            if process and process.poll() is None:
                try:
                    chunk = process.stdout.read(4096)
                    if self._seeking.is_set():
                        # Data arrived just as a seek started — discard it.
                        continue
                    if chunk:
                        self._audio_queue.put(chunk, timeout=0.1)
                        chunks_decoded += 1
                        if chunks_decoded % 100 == 0:
                            logger.debug(
                                "Decoded %d audio chunks, queue=%d",
                                chunks_decoded, self._audio_queue.qsize(),
                            )
                    else:
                        logger.info("Audio decode reached end of stream")
                        break
                except Exception as e:
                    logger.warning("Audio decode error: %s", e)
                    time.sleep(0.01)
            else:
                logger.debug("Decode process not running, waiting...")
                time.sleep(0.01)

        logger.info("Audio decode thread exiting")

    def _start_decode_process(self, start_pos: float):
        """Launch (or relaunch) the ffmpeg subprocess from *start_pos*."""
        if self._decode_process:
            logger.info(
                "Killing existing decode process (pid=%d)",
                self._decode_process.pid,
            )
            self._decode_process.kill()
            try:
                self._decode_process.wait(timeout=1.0)
                logger.info("Old decode process terminated")
            except subprocess.TimeoutExpired:
                logger.warning("Old decode process did not terminate cleanly")

        logger.info("Starting audio decode at position %.2fs", start_pos)

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        cmd = [
            "ffmpeg",
            "-ss", str(start_pos),
            "-i",  self.video_path,
            "-f",  "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate),
            "-ac", str(self.channels),
            "-",
        ]

        self._decode_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            bufsize=4096,
        )
        logger.info(
            "Audio decode process started (pid=%d)", self._decode_process.pid
        )
        self._decode_position = start_pos

    def _handle_seek(self, position: float, generation: int):
        """Drain the queue and restart decoding at the new position."""
        logger.info(
            "Audio handling seek: pos=%.2fs gen=%d", position, generation
        )
        # Gate the decode thread so it stops reading from the old process
        # before we kill it and replace _decode_process.
        self._seeking.set()
        cleared = 0
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        logger.info("Cleared %d chunks from audio queue", cleared)

        self._start_decode_process(position)
        self._current_seek_gen = generation
        self._seeking.clear()
        logger.info("Audio seek complete: gen now %d", self._current_seek_gen)

    # ------------------------------------------------------------------
    # sounddevice callback
    # ------------------------------------------------------------------

    def _audio_callback(self, outdata, frames, time, status):
        """
        Called by sounddevice on a dedicated C thread — must return quickly.

        sounddevice RawOutputStream passes a writable buffer (outdata) that
        we fill in-place.  Volume is applied by scaling the raw int16 PCM
        samples.  Muting or pausing writes silence so we never output stale
        audio.

        Unlike the old PyAudio callback there is no return value; errors are
        signalled by raising sd.CallbackStop / sd.CallbackAbort.
        """
        self._callback_count += 1

        if status:
            logger.warning("sounddevice callback status: %s", status)

        bytes_needed = frames * self.channels * self.sample_width

        # ── silence when paused or muted ──────────────────────────────────
        if not self._is_playing_mirror or self._muted:
            self._silence_count += 1
            if self._silence_count % 100 == 0:
                logger.debug(
                    "Audio callback: silence (paused or muted), count=%d",
                    self._silence_count,
                )
            outdata[:] = bytes(bytes_needed)
            return

        if self._silence_count > 0:
            logger.debug(
                "Audio resuming after %d silent callbacks", self._silence_count
            )
            self._silence_count = 0

        # ── collect enough bytes from the queue ───────────────────────────
        output = b""
        chunks_retrieved = 0
        while len(output) < bytes_needed:
            try:
                output += self._audio_queue.get_nowait()
                chunks_retrieved += 1
            except queue.Empty:
                padding = bytes_needed - len(output)
                if self._callback_count % 50 == 0:
                    logger.warning(
                        "Audio queue empty — padding %d bytes "
                        "(%d chunks before empty)",
                        padding, chunks_retrieved,
                    )
                output += bytes(padding)
                break

        output = output[:bytes_needed]

        # ── apply volume ──────────────────────────────────────────────────
        output = self._apply_volume(output)

        if chunks_retrieved > 0 and self._callback_count % 200 == 0:
            logger.debug(
                "Audio callback: retrieved %d chunks from queue",
                chunks_retrieved,
            )

        outdata[:] = output

    # ------------------------------------------------------------------
    # PCM volume scaling
    # ------------------------------------------------------------------

    @staticmethod
    def _scale_sample(sample: int, factor: float) -> int:
        """Clamp a scaled int16 sample to [-32768, 32767]."""
        return max(-32768, min(32767, int(sample * factor)))

    def _apply_volume(self, raw: bytes) -> bytes:
        """
        Scale every int16 PCM sample in *raw* by ``self._volume``.

        A volume of 1.0 is a no-op (fast path).  Uses stdlib ``array`` so
        no NumPy dependency is required — still fast enough for 44.1 kHz
        stereo at typical buffer sizes (~1 024 frames = 4 096 bytes).
        """
        volume = self._volume          # snapshot once for this buffer
        if volume == 1.0:
            return raw

        samples = array.array("h", raw)          # 'h' = signed short (int16)
        for i in range(len(samples)):
            samples[i] = self._scale_sample(samples[i], volume)
        return bytes(samples)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self):
        """Release all sounddevice and subprocess resources."""
        logger.info("Audio cleanup starting")
        # Unblock the decode thread if it is waiting on a full queue.
        self._seeking.set()
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        if self._stream:
            self._stream.stop()
            self._stream.close()
            logger.info("Audio stream closed")
            # sounddevice manages the PortAudio session globally — no
            # per-instance terminate() call is needed (unlike PyAudio).
        if self._decode_process:
            self._decode_process.kill()
            logger.info("Audio decode process killed")