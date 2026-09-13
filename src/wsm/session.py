"""Data structures that describe a work session."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID


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
