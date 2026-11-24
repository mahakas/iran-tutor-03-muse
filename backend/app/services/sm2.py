"""Deterministic SM-2 spaced-repetition scheduler (Phase 3).

Student-facing ratings map to SM-2 quality grades as follows:

    1 فراموش کردم  -> q=0  (lapse: repetitions reset, review again tomorrow)
    2 سخت          -> q=3  (recalled with difficulty; ease drops)
    3 خوب          -> q=4  (recalled; ease unchanged)
    4 آسان         -> q=5  (effortless; ease grows)

The function is pure: it takes the previous state and a timestamp and returns
the next state. No randomness, no I/O, so every interval is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3
VALID_RATINGS: tuple[int, ...] = (1, 2, 3, 4)
RATING_LABELS_FA: dict[int, str] = {
    1: "فراموش کردم",
    2: "سخت",
    3: "خوب",
    4: "آسان",
}
_RATING_TO_QUALITY: dict[int, int] = {1: 0, 2: 3, 3: 4, 4: 5}


@dataclass(frozen=True)
class SchedulerState:
    ease_factor: float = DEFAULT_EASE_FACTOR
    interval_days: int = 0
    repetitions: int = 0


@dataclass(frozen=True)
class ScheduleResult:
    ease_factor: float
    interval_days: int
    repetitions: int
    next_review_at: datetime
    last_rating: int


def rating_to_quality(rating: int) -> int:
    if rating not in _RATING_TO_QUALITY:
        raise ValueError("rating must be one of 1, 2, 3, 4")
    return _RATING_TO_QUALITY[rating]


def next_ease_factor(ease_factor: float, quality: int) -> float:
    """Classic SM-2 ease update, floored at 1.3."""
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    return max(MIN_EASE_FACTOR, round(ease_factor + delta, 4))


def schedule_review(state: SchedulerState, rating: int, now: datetime) -> ScheduleResult:
    """Apply one SM-2 review and return the new scheduling state.

    - q < 3 (rating 1): repetitions reset to 0 and the card returns in 1 day.
    - q >= 3: repetitions increase; interval is 1 day, then 6 days, then
      ``round(previous_interval * ease_factor)``.
    """
    quality = rating_to_quality(rating)
    ease = next_ease_factor(state.ease_factor, quality)
    if quality < 3:
        repetitions = 0
        interval = 1
    else:
        repetitions = state.repetitions + 1
        if repetitions == 1:
            interval = 1
        elif repetitions == 2:
            interval = 6
        else:
            interval = max(1, round(state.interval_days * ease))
    return ScheduleResult(
        ease_factor=ease,
        interval_days=interval,
        repetitions=repetitions,
        next_review_at=now + timedelta(days=interval),
        last_rating=rating,
    )


__all__ = [
    "DEFAULT_EASE_FACTOR",
    "MIN_EASE_FACTOR",
    "RATING_LABELS_FA",
    "VALID_RATINGS",
    "ScheduleResult",
    "SchedulerState",
    "next_ease_factor",
    "rating_to_quality",
    "schedule_review",
]
