"""
playback_state.py
=================
Thread-safe playback state manager for coordinating video and audio workers.

Public contract (unchanged):
    PlaybackStateManager
        .start_playback()
        .stop_playback()
        .pause()
        .resume()
        .seek(position_sec) -> int          # returns new seek generation
        .get_current_position() -> float    # seconds from start
        .get_state() -> PlaybackState
        .is_running() -> bool
        .is_playing() -> bool
        .set_reverse(enabled)
        .is_reverse() -> bool
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State snapshot (replaces raw dict – typed, immutable, introspectable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlaybackState:
    """
    Immutable snapshot of playback state at a point in time.

    Returned by :meth:`PlaybackStateManager.get_state`.

    Supports *both* attribute access and dict-style subscript access so that
    existing callers using ``state["position"]`` continue to work unchanged,
    while new callers can use the typed ``state.position`` form::

        state = manager.get_state()
        state.position          # attribute access  (new)
        state["position"]       # subscript access  (backward-compatible)
    """
    running: bool
    playing: bool
    reverse: bool
    position: float          # seconds
    seek_generation: int

    def __getitem__(self, key: str):
        if key not in self.__dataclass_fields__:
            raise KeyError(key)
        return getattr(self, key)


# ---------------------------------------------------------------------------
# Internal clock helpers (pure functions – easy to test in isolation)
# ---------------------------------------------------------------------------

def _elapsed_playing_time(
    start_time: float,
    accumulated_pause: float,
    reference_time: float | None = None,
) -> float:
    """
    Return how many seconds of *playing* (non-paused) time have elapsed since
    *start_time*, discounting *accumulated_pause* seconds of pause time.

    Args:
        start_time:         Wall-clock time when the current play segment began
                            (result of ``time.time()``).
        accumulated_pause:  Total seconds already spent in previous pauses.
        reference_time:     Override "now" – useful for paused position queries
                            where we want elapsed *up to the moment of pause*
                            rather than up to the current instant.
    """
    now = reference_time if reference_time is not None else time.time()
    return now - start_time - accumulated_pause


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class PlaybackStateManager:
    """
    Centralised, thread-safe state manager for coordinating playback workers.

    Responsibilities
    ----------------
    * Track whether playback is active, playing, or paused.
    * Maintain an accurate wall-clock-based position counter.
    * Coordinate seeks via a monotonically increasing *seek generation* so
      workers can detect stale work cheaply (``if gen != my_gen: discard``).
    * Guard all mutations with a reentrant lock so callers are not required to
      synchronise externally.

    Position model
    --------------
    The position is derived entirely from wall-clock time – there is no
    accumulator that drifts.  The formula is::

        position = seek_position + (wall_now - start_time - pause_time)

    where ``start_time`` is reset on every seek/start and ``pause_time``
    accumulates pause durations within the current seek segment.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # Lifecycle flags
        self._running: bool = False
        self._playing: bool = False
        self._reverse: bool = False

        # Position tracking
        self._seek_position: float = 0.0     # position at last seek / start
        self._start_time: float | None = None   # wall clock at last seek / resume
        self._accumulated_pause: float = 0.0  # total pause seconds this segment
        self._pause_started_at: float | None = None  # wall clock when paused

        # Seek coordination
        self._seek_generation: int = 0

    # ------------------------------------------------------------------
    # Lifecycle control
    # ------------------------------------------------------------------

    def start_playback(self) -> None:
        """Begin playback from position 0 (or the last seeked position)."""
        with self._lock:
            logger.info("START PLAYBACK")
            self._running = True
            self._playing = True
            self._seek_generation += 1
            self._start_time = time.time()
            self._accumulated_pause = 0.0
            self._pause_started_at = None

    def stop_playback(self) -> None:
        """Halt playback entirely.  Position is preserved for inspection."""
        with self._lock:
            logger.info("STOP PLAYBACK")
            self._running = False
            self._playing = False
            if self._pause_started_at is None:
                self._pause_started_at = time.time()

    # ------------------------------------------------------------------
    # Play / pause
    # ------------------------------------------------------------------

    def pause(self) -> None:
        """
        Pause playback.

        Idempotent: calling while already paused has no effect.
        Has no effect if playback has not been started.
        """
        with self._lock:
            if not self._playing:
                return
            logger.info("PAUSE  pos=%.3fs", self._position_locked())
            self._playing = False
            self._pause_started_at = time.time()

    def resume(self) -> None:
        """
        Resume from a paused state.

        Idempotent: calling while already playing has no effect.
        Has no effect if the manager is not running.
        """
        with self._lock:
            if self._playing or not self._running:
                return
            if self._pause_started_at is not None:
                self._accumulated_pause += time.time() - self._pause_started_at
                self._pause_started_at = None
            logger.info("RESUME pos=%.3fs", self._position_locked())
            self._playing = True

    # ------------------------------------------------------------------
    # Seeking
    # ------------------------------------------------------------------

    def seek(self, position_sec: float) -> int:
        """
        Jump to *position_sec* (seconds from the beginning of the media).

        Resets the wall-clock anchor and clears accumulated pause time so the
        position formula stays accurate after the jump.

        Returns:
            The new seek generation counter.  Workers should compare this
            against the generation they captured at the start of a work unit;
            if the values differ the work is stale and should be discarded.
        """
        with self._lock:
            prev_gen = self._seek_generation
            self._seek_position = position_sec
            self._seek_generation += 1
            self._start_time = time.time()
            self._accumulated_pause = 0.0
            self._pause_started_at = None
            logger.info(
                "SEEK   pos=%.3fs  gen %d -> %d",
                position_sec, prev_gen, self._seek_generation,
            )
            return self._seek_generation

    # ------------------------------------------------------------------
    # Position query
    # ------------------------------------------------------------------

    def get_current_position(self) -> float:
        """
        Return the current playback position in seconds.

        The value is derived from wall-clock time, not from a polled counter,
        so it is accurate between calls without any external updates.
        """
        with self._lock:
            return self._position_locked()

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def get_state(self) -> PlaybackState:
        """
        Return an immutable snapshot of the current playback state.

        The snapshot is self-consistent: all fields are captured under the same
        lock acquisition, so callers see a coherent view even if another thread
        mutates state immediately after this call returns.
        """
        with self._lock:
            return PlaybackState(
                running=self._running,
                playing=self._playing,
                reverse=self._reverse,
                position=self._position_locked(),
                seek_generation=self._seek_generation,
            )

    # ------------------------------------------------------------------
    # Convenience accessors (avoid taking the lock twice for callers
    # who only need a single flag)
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Return ``True`` if playback has been started and not stopped."""
        with self._lock:
            return self._running

    def is_playing(self) -> bool:
        """Return ``True`` if actively advancing (not paused, not stopped)."""
        with self._lock:
            return self._playing

    def set_reverse(self, enabled: bool) -> None:
        """Enable or disable reverse playback mode."""
        with self._lock:
            logger.info("REVERSE %s", "on" if enabled else "off")
            self._reverse = enabled

    def is_reverse(self) -> bool:
        """Return ``True`` if reverse playback mode is active."""
        with self._lock:
            return self._reverse

    # ------------------------------------------------------------------
    # Internal helpers  (must be called with self._lock already held)
    # ------------------------------------------------------------------

    def _position_locked(self) -> float:
        """
        Compute the current position.  **Caller must hold** ``self._lock``.

        Three distinct cases:
        1. Playback has never started (``_start_time`` is None) → return the
           raw seek position (default 0.0, or wherever the last seek landed).
        2. Currently playing → elapsed time advances to *now*.
        3. Currently paused → elapsed time is frozen at the moment of pause
           (``_pause_started_at``), so the reported position does not creep.
        """
        if self._start_time is None:
            return self._seek_position

        if self._playing:
            # Active playback: measure elapsed up to right now.
            elapsed = _elapsed_playing_time(self._start_time, self._accumulated_pause)
        else:
            # Paused or stopped: elapsed is frozen at the moment we paused/stopped.
            # After a seek, _pause_started_at is always None (cleared by seek()),
            # so return _seek_position directly — no warning needed.
            if self._pause_started_at is None:
                return self._seek_position
            elapsed = _elapsed_playing_time(
                self._start_time,
                self._accumulated_pause,
                reference_time=self._pause_started_at,
            )

        return self._seek_position + elapsed

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover
        state = self.get_state()
        return (
            f"<PlaybackStateManager "
            f"running={state.running} playing={state.playing} "
            f"pos={state.position:.3f}s gen={state.seek_generation}>"
        )