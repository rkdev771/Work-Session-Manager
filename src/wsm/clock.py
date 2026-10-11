"""The single boundary for capturing command time."""

from collections.abc import Callable
from datetime import datetime, timezone


Clock = Callable[[], datetime]


class ClockError(ValueError):
    """The current clock cannot be used with the saved timestamps."""


def capture_time(clock: Clock | None = None) -> datetime:
    """Capture an aware instant and discard fractions after converting to UTC."""
    value = clock() if clock is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ClockError("The system clock must supply a timezone-aware datetime.")
    return value.astimezone(timezone.utc).replace(microsecond=0)
