"""
audio_stream_worker.py
======================

Audio decoder backend selection
---------------------------------
  ffmpeg CLI found   →  _FfmpegProcess  (subprocess, zero extra deps)
  ffmpeg CLI absent  →  _PyAvProcess    (PyAV, bundles libav in its wheel)

The two classes share the same duck-typed interface as subprocess.Popen
(.stdout, .poll(), .pid, .kill(), .wait()) so _decode_audio never needs
to know which backend is active.

Install
-------
    pip install av          # PyAV — cross-platform, no ffmpeg binary needed
    pip install sounddevice
"""

from __future__ import annotations

import array
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from typing import Optional

import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal

from qtgui.video.worker.state import PlaybackStateManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decoder back-end selection
# ---------------------------------------------------------------------------

_FFMPEG_BIN: Optional[str] = shutil.which("ffmpeg")


# ===========================================================================
# Back-end A: ffmpeg subprocess  (preferred when ffmpeg is on PATH)
# ===========================================================================

class _FfmpegProcess:
    """
    Thin wrapper around a ffmpeg subprocess that decodes one audio stream to
    raw s16le PCM on stdout.

    Presents the same interface as _PyAvProcess so AudioStreamWorker
    can treat them identically.
    """

    def __init__(
        self,
        video_path: str,
        start_pos: float,
        sample_rate: int,
        channels: int,
    ) -> None:
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        cmd = [
            _FFMPEG_BIN,
            "-ss", str(start_pos),
            "-i",  video_path,
            "-f",  "s16le",
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            bufsize=4096,
        )
        self.stdout = self._proc.stdout
        self.pid    = self._proc.pid

    def poll(self) -> Optional[int]:
        return self._proc.poll()

    def kill(self) -> None:
        self._proc.kill()

    def wait(self, timeout: Optional[float] = None) -> int:
        return self._proc.wait(timeout=timeout)


# ===========================================================================
# Back-end B: PyAV  (no ffmpeg binary required — libav bundled in wheel)
# ===========================================================================

class _PyAvReader:
    """
    Buffered, blocking file-like reader wrapping PyAV frame decoding.

    read(n) blocks until n bytes of s16le PCM are available or the stream
    is exhausted (returns b'' on EOF, matching subprocess.stdout behaviour).
    """

    def __init__(
        self,
        video_path: str,
        start_pos: float,
        sample_rate: int,
        channels: int,
    ) -> None:
        import av  # local import — only required when ffmpeg is absent

        self._exhausted = False
        self._buffer    = bytearray()

        self._container = av.open(video_path)
        self._resampler = av.AudioResampler(
            format = "s16",
            layout = "stereo" if channels == 2 else "mono",
            rate   = sample_rate,
        )

        if not self._container.streams.audio:
            raise RuntimeError(f"No audio stream found in {video_path!r}")

        # Seek before creating the decode generator.
        # av.time_base == Fraction(1, 1_000_000); container.seek() expects µs.
        if start_pos > 0:
            self._container.seek(int(start_pos * 1_000_000))

        self._frames = self._container.decode(audio=0)

    # -- file-like interface ------------------------------------------------

    def read(self, n: int) -> bytes:
        """Block until n bytes are buffered, then return exactly n bytes."""
        while len(self._buffer) < n and not self._exhausted:
            self._pull_frame()

        chunk = bytes(self._buffer[:n])
        del self._buffer[:n]
        return chunk  # empty bytes signals EOF — same as subprocess.stdout

    def close(self) -> None:
        self._exhausted = True
        try:
            self._container.close()
        except Exception:
            pass

    # -- internal -----------------------------------------------------------

    def _pull_frame(self) -> None:
        try:
            frame = next(self._frames)
        except StopIteration:
            self._flush_resampler()
            self._exhausted = True
            return
        except Exception as exc:
            logger.warning("PyAV decode error: %s", exc)
            self._exhausted = True
            return

        self._resample_into_buffer(frame)

    def _flush_resampler(self) -> None:
        """Drain any samples still held inside the resampler."""
        try:
            result = self._resampler.resample(None)
            self._collect_resampled(result)
        except Exception:
            pass

    def _resample_into_buffer(self, frame) -> None:
        try:
            result = self._resampler.resample(frame)
            self._collect_resampled(result)
        except Exception as exc:
            logger.warning("PyAV resample error: %s", exc)

    def _collect_resampled(self, result) -> None:
        # resample() returns a list in PyAV >= 9, a single frame in older versions.
        frames = result if isinstance(result, list) else ([result] if result else [])
        for f in frames:
            if f is None:
                continue
            for plane in f.planes:
                self._buffer.extend(bytes(plane))


class _PyAvProcess:
    """
    Drop-in replacement for _FfmpegProcess backed by PyAV.

    Presents the same duck-typed interface (.stdout, .poll(), .pid,
    .kill(), .wait()) so AudioStreamWorker._decode_audio requires
    zero changes when this backend is active.
    """

    _EOF = 0   # return-code sentinel used by poll() after stream ends

    def __init__(
        self,
        video_path: str,
        start_pos: float,
        sample_rate: int,
        channels: int,
    ) -> None:
        self.stdout = _PyAvReader(video_path, start_pos, sample_rate, channels)
        self.pid    = id(self)   # no OS-level PID; object id serves as a label

    def poll(self) -> Optional[int]:
        """Return None while data remains, 0 once the stream is exhausted."""
        return self._EOF if self.stdout._exhausted else None

    def kill(self) -> None:
        self.stdout.close()

    def wait(self, timeout: Optional[float] = None) -> int:
        return self._EOF   # no real process to wait for


# ===========================================================================
# Factory
# ===========================================================================

def _make_decoder(
    video_path: str,
    start_pos: float,
    sample_rate: int,
    channels: int,
) -> _FfmpegProcess | _PyAvProcess:
    """
    Return the best available decoder.

    Priority: ffmpeg CLI subprocess → PyAV (bundled libav)
    """
    if _FFMPEG_BIN:
        logger.debug("Using ffmpeg subprocess decoder (%s)", _FFMPEG_BIN)
        return _FfmpegProcess(video_path, start_pos, sample_rate, channels)

    logger.debug("ffmpeg not on PATH — falling back to PyAV decoder")
    try:
        return _PyAvProcess(video_path, start_pos, sample_rate, channels)
    except ImportError:
        raise RuntimeError(
            "No audio decoder available.\n"
            "Either install ffmpeg (https://ffmpeg.org/download.html)\n"
            "or install PyAV:  pip install av"
        )


# ===========================================================================
# Worker
# ===========================================================================

class AudioStreamWorker(QObject):
    """
    Audio worker with seek/pause synchronisation via PlaybackStateManager,
    and volume/mute control via the VolumeWidget signals.

    Wiring up the volume widget
    ---------------------------
        vol_widget.volume_changed.connect(worker.set_volume)
        vol_widget.mute_changed.connect(worker.set_muted)
    """

    position_changed = pyqtSignal(float)
    finished         = pyqtSignal()
    error_occurred   = pyqtSignal(str)

    def __init__(self, video_path: str, state_manager: PlaybackStateManager):
        super().__init__()
        self.video_path = video_path
        self.state      = state_manager

        self.sample_rate  = 44100
        self.channels     = 2
        self.sample_width = 2   # bytes per sample — matches int16

        self._stream:         Optional[sd.RawOutputStream]             = None
        self._decode_process: Optional[_FfmpegProcess | _PyAvProcess] = None
        self._audio_queue:    queue.Queue[bytes]                       = queue.Queue(maxsize=100)

        self._current_seek_gen = 0
        self._decode_position  = 0.0

        self._volume:            float = 1.0
        self._muted:             bool  = False
        self._is_playing_mirror: bool  = False

        self._seeking = threading.Event()

        self._callback_count = 0
        self._silence_count  = 0

    # ------------------------------------------------------------------
    # Public volume API
    # ------------------------------------------------------------------

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        logger.debug("Audio volume set to %.2f", self._volume)

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        logger.debug("Audio muted=%s", muted)

    # ------------------------------------------------------------------
    # Worker entry point
    # ------------------------------------------------------------------

    def run(self):
        logger.info(
            "Audio worker starting (decoder: %s)",
            "ffmpeg" if _FFMPEG_BIN else "PyAV",
        )
        try:
            decode_thread = threading.Thread(
                target=self._decode_audio, daemon=True
            )
            decode_thread.start()
            logger.info("Decode thread started")

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
                self._is_playing_mirror = state.playing

                if state.seek_generation != self._current_seek_gen:
                    logger.info(
                        "Seek detected: gen %d -> %d, pos=%.2fs",
                        self._current_seek_gen, state.seek_generation, state.position,
                    )
                    self._handle_seek(state.position, state.seek_generation)

                if loop_count % 20 == 0:
                    logger.debug(
                        "Monitor: playing=%s pos=%.2fs queue=%d "
                        "callbacks=%d silence=%d vol=%.2f muted=%s alive=%s",
                        state.playing, state.position,
                        self._audio_queue.qsize(),
                        self._callback_count, self._silence_count,
                        self._volume, self._muted,
                        self._decode_process and self._decode_process.poll() is None,
                    )

                if loop_count % 5 == 0:
                    self.position_changed.emit(state.position)

                loop_count += 1
                time.sleep(0.05)

        except Exception as e:
            logger.error("Audio worker error: %s", e, exc_info=True)
            self.error_occurred.emit(str(e))
        finally:
            self._cleanup()

    # ------------------------------------------------------------------
    # Decode thread  — identical for both backends
    # ------------------------------------------------------------------

    def _decode_audio(self):
        logger.info("Decode thread starting")
        self._start_decode_process(0.0)

        chunks_decoded = 0
        last_seek_gen  = self._current_seek_gen

        while self.state.is_running():
            if self._seeking.is_set():
                time.sleep(0.01)
                continue

            state = self.state.get_state()
            if state.seek_generation != last_seek_gen:
                last_seek_gen = state.seek_generation

            process = self._decode_process
            if process and process.poll() is None:
                try:
                    chunk = process.stdout.read(4096)
                    if self._seeking.is_set():
                        continue
                    if chunk:
                        self._audio_queue.put(chunk, timeout=0.1)
                        chunks_decoded += 1
                        if chunks_decoded % 100 == 0:
                            logger.debug(
                                "Decoded %d chunks, queue=%d",
                                chunks_decoded, self._audio_queue.qsize(),
                            )
                    else:
                        logger.info("Decode reached end of stream")
                        break
                except Exception as e:
                    logger.warning("Decode error: %s", e)
                    time.sleep(0.01)
            else:
                logger.debug("Decoder not running, waiting...")
                time.sleep(0.01)

        logger.info("Decode thread exiting")

    def _start_decode_process(self, start_pos: float):
        if self._decode_process:
            logger.info("Stopping existing decoder (pid=%s)", self._decode_process.pid)
            self._decode_process.kill()
            try:
                self._decode_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                logger.warning("Old decoder did not exit cleanly")

        logger.info("Starting decoder at %.2fs", start_pos)
        self._decode_process = _make_decoder(
            self.video_path, start_pos, self.sample_rate, self.channels
        )
        logger.info("Decoder ready (pid=%s)", self._decode_process.pid)
        self._decode_position = start_pos

    def _handle_seek(self, position: float, generation: int):
        logger.info("Handling seek: pos=%.2fs gen=%d", position, generation)
        self._seeking.set()
        cleared = 0
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        logger.info("Cleared %d chunks from queue", cleared)
        self._start_decode_process(position)
        self._current_seek_gen = generation
        self._seeking.clear()
        logger.info("Seek complete: gen=%d", self._current_seek_gen)

    # ------------------------------------------------------------------
    # sounddevice callback
    # ------------------------------------------------------------------

    def _audio_callback(self, outdata, frames, time, status):
        self._callback_count += 1

        if status:
            logger.warning("sounddevice status: %s", status)

        bytes_needed = frames * self.channels * self.sample_width

        if not self._is_playing_mirror or self._muted:
            self._silence_count += 1
            if self._silence_count % 100 == 0:
                logger.debug("Silence count=%d", self._silence_count)
            outdata[:] = bytes(bytes_needed)
            return

        if self._silence_count > 0:
            logger.debug("Resuming after %d silent callbacks", self._silence_count)
            self._silence_count = 0

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
                        "Queue empty — padding %d bytes (%d chunks retrieved)",
                        padding, chunks_retrieved,
                    )
                output += bytes(padding)
                break

        output = output[:bytes_needed]
        outdata[:] = self._apply_volume(output)

    # ------------------------------------------------------------------
    # PCM volume scaling
    # ------------------------------------------------------------------

    @staticmethod
    def _scale_sample(sample: int, factor: float) -> int:
        return max(-32768, min(32767, int(sample * factor)))

    def _apply_volume(self, raw: bytes) -> bytes:
        volume = self._volume
        if volume == 1.0:
            return raw
        samples = array.array("h", raw)
        for i in range(len(samples)):
            samples[i] = self._scale_sample(samples[i], volume)
        return bytes(samples)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self):
        logger.info("Audio cleanup starting")
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
        if self._decode_process:
            self._decode_process.kill()
            logger.info("Decoder stopped")