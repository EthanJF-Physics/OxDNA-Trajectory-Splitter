"""Small dependency-free terminal progress/timing display for long CLI operations."""
from __future__ import annotations

import sys
import time
from typing import TextIO


class ProgressDisplay:
    """Render one rate-limited progress line with elapsed time and ETA."""

    def __init__(self, *, enabled: bool = True, stream: TextIO | None = None, width: int = 20) -> None:
        self.stream = stream or sys.stderr
        self.enabled = bool(enabled and getattr(self.stream, "isatty", lambda: False)())
        self.width = width
        self._stage: str | None = None
        self._started = 0.0
        self._last_render = 0.0

    @staticmethod
    def _clock(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"

    def update(self, stage: str, current: int, total: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if stage != self._stage:
            if self._stage is not None:
                self.stream.write("\n")
            self._stage = stage
            self._started = now
            self._last_render = 0.0
        total = max(int(total), 1)
        current = min(max(int(current), 0), total)
        if current < total and self._last_render and now - self._last_render < 0.10:
            return
        self._last_render = now
        fraction = current / total
        filled = min(self.width, int(fraction * self.width))
        bar = "#" * filled + "-" * (self.width - filled)
        elapsed = now - self._started
        eta = ""
        if current > 0 and current < total and elapsed > 0:
            remaining = elapsed * (total - current) / current
            eta = f"  ~{self._clock(remaining)} left"
        line = f"\r{stage:<22} [{bar}] {fraction:6.1%}  {self._clock(elapsed)} elapsed{eta}"
        self.stream.write(line)
        self.stream.flush()
        if current >= total:
            self.stream.write("\n")
            self.stream.flush()
            self._stage = None

    def finish(self) -> None:
        if self.enabled and self._stage is not None:
            self.stream.write("\n")
            self.stream.flush()
            self._stage = None
