from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.config import ScoringConfig


def parse_iso(value: str) -> float:
    """Parse ISO 8601 into event-time epoch seconds. Naive timestamps are UTC."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class Watermark:
    """Monotonic event-time watermark. Never retreats, never uses wall clock."""

    def __init__(self, window_seconds: float, inclusive: bool) -> None:
        self.window_seconds = window_seconds
        self.inclusive = inclusive
        self.value: Optional[float] = None

    def advance(self, event_time: float) -> None:
        if self.value is None or event_time > self.value:
            self.value = event_time

    def cutoff(self) -> Optional[float]:
        if self.value is None:
            return None
        return self.value - self.window_seconds

    def is_expired(self, created_at: float) -> bool:
        bound = self.cutoff()
        if bound is None:
            return False
        if self.inclusive:
            return created_at < bound
        return created_at <= bound

    def reset(self) -> None:
        self.value = None


def watermark_from_config(cfg: ScoringConfig) -> Watermark:
    return Watermark(cfg.WINDOW_SECONDS, cfg.WINDOW_BOUNDARY_INCLUSIVE)
