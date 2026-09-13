"""Data structures that describe a work session."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID


SCHEMA_VERSION = 1


def _validate_required_text(value: object, field_name: str) -> None:
    """Require a non-empty string for a text field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _validate_utc_datetime(value: object, field_name: str) -> None:
    """Require a timezone-aware datetime whose UTC offset is zero."""
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be a timezone-aware UTC datetime.")


def _validate_duration(
    value: object,
    field_name: str,
    *,
    required: bool = False,
) -> None:
    """Require an optional or required non-negative whole number of seconds."""
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required for a closed session.")
        return

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")


def _datetime_to_json(value: datetime | None) -> str | None:
    """Convert an optional datetime into an ISO 8601 JSON value."""
    if value is None:
        return None
    return value.isoformat()


def _datetime_from_json(value: str | None) -> datetime | None:
    """Convert an optional ISO 8601 JSON value into a datetime."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


class SessionState(str, Enum):
    """The four lifecycle states allowed for a work session."""

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


@dataclass(kw_only=True)
class Pause:
    """A recorded break from active work."""

    started_at: datetime
    ended_at: datetime | None
    reason: str
    duration_seconds: int | None = None

    def validate(self) -> None:
        """Raise ValueError when this pause has an invalid stored shape."""
        _validate_utc_datetime(self.started_at, "Pause started_at")
        if self.ended_at is not None:
            _validate_utc_datetime(self.ended_at, "Pause ended_at")
        _validate_required_text(self.reason, "Pause reason")
        _validate_duration(self.duration_seconds, "Pause duration_seconds")

        if self.ended_at is None and self.duration_seconds is not None:
            raise ValueError("An open pause cannot have a duration_seconds value.")

    def to_dict(self) -> dict[str, Any]:
        """Return this pause as JSON-compatible Python data."""
        self.validate()
        data = {
            "started_at": _datetime_to_json(self.started_at),
            "ended_at": _datetime_to_json(self.ended_at),
            "reason": self.reason,
        }
        if self.duration_seconds is not None:
            data["duration_seconds"] = self.duration_seconds
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pause":
        """Build a pause from JSON-compatible Python data."""
        try:
            pause = cls(
                started_at=_datetime_from_json(data["started_at"]),
                ended_at=_datetime_from_json(data["ended_at"]),
                reason=data["reason"],
                duration_seconds=data.get("duration_seconds"),
            )
            pause.validate()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid pause data: {error}") from error

        return pause


@dataclass(kw_only=True)
class Session:
    """The information belonging to one work session."""

    id: UUID
    name: str
    goal: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    pauses: list[Pause] = field(default_factory=list)
    goal_completed: bool | None = None
    notes: str | None = None
    active_duration_seconds: int | None = None
    paused_duration_seconds: int | None = None
    total_duration_seconds: int | None = None

    @property
    def state(self) -> SessionState:
        """Derive the lifecycle state from the session's timestamps and pauses."""
        if self.ended_at is not None:
            return SessionState.CLOSED

        if self.started_at is None:
            return SessionState.CREATED

        if self.pauses and self.pauses[-1].ended_at is None:
            return SessionState.PAUSED

        return SessionState.ACTIVE

    def validate(self) -> None:
        """Raise ValueError when this session has an invalid stored shape."""
        if not isinstance(self.id, UUID) or self.id.version != 4:
            raise ValueError("Session id must be a UUIDv4.")
        _validate_required_text(self.name, "Session name")
        _validate_required_text(self.goal, "Session goal")

        if self.started_at is not None:
            _validate_utc_datetime(self.started_at, "Session started_at")
        if self.ended_at is not None:
            _validate_utc_datetime(self.ended_at, "Session ended_at")

        if not isinstance(self.pauses, list):
            raise ValueError("Session pauses must be a list.")
        for pause in self.pauses:
            if not isinstance(pause, Pause):
                raise ValueError("Every session pause must be a Pause object.")
            pause.validate()

        if self.goal_completed is not None and not isinstance(
            self.goal_completed, bool
        ):
            raise ValueError("Session goal_completed must be a boolean or None.")
        if self.notes is not None and not isinstance(self.notes, str):
            raise ValueError("Session notes must be a string or None.")

        duration_fields = (
            (self.active_duration_seconds, "Session active_duration_seconds"),
            (self.paused_duration_seconds, "Session paused_duration_seconds"),
            (self.total_duration_seconds, "Session total_duration_seconds"),
        )
        for value, field_name in duration_fields:
            _validate_duration(value, field_name)

        closing_values = (
            self.goal_completed,
            self.notes,
            self.active_duration_seconds,
            self.paused_duration_seconds,
            self.total_duration_seconds,
        )

        if self.started_at is None:
            if self.ended_at is not None:
                raise ValueError("A session cannot end before it has started.")
            if self.pauses:
                raise ValueError("A created session cannot contain pauses.")
            if any(value is not None for value in closing_values):
                raise ValueError("A created session cannot contain closing data.")
            return

        open_pause_indexes = [
            index for index, pause in enumerate(self.pauses) if pause.ended_at is None
        ]
        if open_pause_indexes and open_pause_indexes != [len(self.pauses) - 1]:
            raise ValueError("Only the most recent pause may be open.")

        if self.ended_at is None:
            if any(value is not None for value in closing_values):
                raise ValueError("A non-closed session cannot contain closing data.")
            return

        if open_pause_indexes:
            raise ValueError("A closed session cannot contain an open pause.")
        if not isinstance(self.goal_completed, bool):
            raise ValueError("A closed session requires goal_completed.")
        if not isinstance(self.notes, str):
            raise ValueError("A closed session requires notes, which may be empty.")
        for value, field_name in duration_fields:
            _validate_duration(value, field_name, required=True)
        for pause in self.pauses:
            _validate_duration(
                pause.duration_seconds,
                "Pause duration_seconds",
                required=True,
            )

    def to_dict(self) -> dict[str, Any]:
        """Return this session as JSON-compatible Python data."""
        self.validate()
        data = {
            "schema_version": SCHEMA_VERSION,
            "id": str(self.id),
            "name": self.name,
            "goal": self.goal,
            "started_at": _datetime_to_json(self.started_at),
            "pauses": [pause.to_dict() for pause in self.pauses],
        }

        if self.state is SessionState.CLOSED:
            data.update(
                {
                    "ended_at": _datetime_to_json(self.ended_at),
                    "active_duration_seconds": self.active_duration_seconds,
                    "paused_duration_seconds": self.paused_duration_seconds,
                    "total_duration_seconds": self.total_duration_seconds,
                    "goal_completed": self.goal_completed,
                    "notes": self.notes,
                }
            )

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        """Build a session from JSON-compatible Python data."""
        schema_version = data.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version: {schema_version!r}")

        try:
            session = cls(
                id=UUID(data["id"]),
                name=data["name"],
                goal=data["goal"],
                started_at=_datetime_from_json(data["started_at"]),
                ended_at=_datetime_from_json(data.get("ended_at")),
                pauses=[Pause.from_dict(pause) for pause in data["pauses"]],
                goal_completed=data.get("goal_completed"),
                notes=data.get("notes"),
                active_duration_seconds=data.get("active_duration_seconds"),
                paused_duration_seconds=data.get("paused_duration_seconds"),
                total_duration_seconds=data.get("total_duration_seconds"),
            )
            session.validate()
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid session data: {error}") from error

        return session
