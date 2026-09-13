"""Data structures that describe a work session."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


SCHEMA_VERSION = 1


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

    def to_dict(self) -> dict[str, Any]:
        """Return this pause as JSON-compatible Python data."""
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
        return cls(
            started_at=_datetime_from_json(data["started_at"]),
            ended_at=_datetime_from_json(data["ended_at"]),
            reason=data["reason"],
            duration_seconds=data.get("duration_seconds"),
        )


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

    def to_dict(self) -> dict[str, Any]:
        """Return this session as JSON-compatible Python data."""
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

        return cls(
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
