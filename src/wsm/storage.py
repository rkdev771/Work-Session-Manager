"""Local JSON persistence for saved sessions and listing selectors."""

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from wsm.clock import Clock, ClockError, capture_time
from wsm.session import Durations, Pause, Session, SessionState


class StorageError(Exception):
    """A storage operation could not safely complete."""


@dataclass(frozen=True, kw_only=True)
class PendingPause:
    """An unsaved candidate bound to a UUID and its original saved bytes."""

    session_id: UUID
    timestamp: datetime
    saved_record: bytes


@dataclass(frozen=True, kw_only=True)
class PendingClose:
    """An unsaved end time bound to the original UUID and saved bytes."""

    session_id: UUID
    timestamp: datetime
    saved_record: bytes


@dataclass(frozen=True, kw_only=True)
class StatusSnapshot:
    """A consistent inventory and calculated ACTIVE status for one command."""

    active: Session | None
    durations: Durations | None
    paused_count: int
    created_count: int


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject ambiguous JSON instead of silently taking its last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


class SessionStore:
    """Store sessions under a stable root, defaulting to ~/.wsm."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path.home() / ".wsm"

    def save_created(self, session: Session) -> None:
        """Persist a new CREATED session without changing listing selectors."""
        try:
            data = session.to_dict()
            if session.state is not SessionState.CREATED:
                raise ValueError("Only new CREATED sessions can be saved here.")
            with self._access():
                path = self.root / "unfinished" / f"{session.id}.json"
                if path.exists() or (self.root / "sessions" / path.name).exists():
                    raise StorageError(f"Session identity already exists: {path.name}")
                self._unfinished_inventory()
                self._write_json(path, data)
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not save session {session.id}: {error}") from error

    def refresh_selectors(self) -> list[tuple[int, Session]]:
        """Persist compact selectors and return their unfinished listing."""
        try:
            with self._access():
                sessions = self._unfinished_inventory()
                sessions.sort(key=lambda session: (session.name, str(session.id)))
                listing = list(enumerate(sessions, start=1))
                self._write_json(
                    self.root / "selectors.json",
                    {str(number): str(session.id) for number, session in listing},
                )
                return listing
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not list sessions: {error}") from error

    def resolve_selector(self, text: str | None) -> Session:
        """Resolve the saved number without rebuilding or guessing selectors."""
        try:
            with self._access():
                return self._resolve_selector(text, self._unfinished_inventory())
        except OSError as error:
            raise StorageError(f"Could not resolve selector: {error} Run wsm sessions.") from error

    def start(self, selector: str | None, *, clock: Clock | None = None) -> Session:
        """Resolve, validate, capture time and persist under one store lock."""
        try:
            with self._access():
                sessions = self._unfinished_inventory()
                selected = self._resolve_selector(selector, sessions)
                if selected.state is SessionState.PAUSED:
                    raise StorageError("This session is PAUSED. Use wsm resume instead.")
                if selected.state is not SessionState.CREATED:
                    raise StorageError("Only CREATED sessions can be started; this session has already started.")
                active = next((session for session in sessions
                               if session.state is SessionState.ACTIVE), None)
                if active is not None:
                    raise StorageError(f"An ACTIVE session already exists: {active.name}. Pause or close it first.")
                selected.started_at = capture_time(clock)
                selected.validate_timing()
                self._write_json(self.root / "unfinished" / f"{selected.id}.json",
                                 selected.to_dict())
                return selected
        except ClockError:
            raise
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not start session: {error}") from error

    def capture_pause(self, *, clock: Clock | None = None) -> PendingPause:
        """Capture time at entry and release store access before user input."""
        timestamp = capture_time(clock)
        try:
            with self._access():
                sessions = self._unfinished_inventory()
                active = next((session for session in sessions
                               if session.state is SessionState.ACTIVE), None)
                if active is None:
                    raise StorageError("No active session to pause.")
                active.durations(timestamp)
                path = self.root / "unfinished" / f"{active.id}.json"
                return PendingPause(session_id=active.id, timestamp=timestamp,
                                    saved_record=path.read_bytes())
        except ClockError:
            raise
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not prepare pause: {error}") from error

    def commit_pause(self, pending: PendingPause, reason: str) -> Session:
        """Save only if the UUID's record is unchanged since capture."""
        try:
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("Pause reason must contain nonwhitespace text.")
            with self._access():
                sessions = self._unfinished_inventory()
                selected = next((session for session in sessions
                                 if session.id == pending.session_id), None)
                path = self.root / "unfinished" / f"{pending.session_id}.json"
                if (selected is None or path.read_bytes() != pending.saved_record
                        or selected.state is not SessionState.ACTIVE):
                    raise StorageError("Session changed while pause input was pending. Run wsm pause again.")
                selected.durations(pending.timestamp)
                selected.pauses.append(Pause(started_at=pending.timestamp,
                                             ended_at=None, reason=reason.strip()))
                selected.validate_timing()
                self._write_json(path, selected.to_dict())
                return selected
        except ClockError:
            raise
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not pause session: {error}") from error

    def capture_close(self, selector: str | None = None, *, clock: Clock | None = None) -> PendingClose:
        """Capture at entry, then release storage access before prompting."""
        timestamp = capture_time(clock)
        try:
            with self._access():
                sessions = self._unfinished_inventory()
                if selector is None:
                    selected = next((session for session in sessions
                                     if session.state is SessionState.ACTIVE), None)
                    if selected is None:
                        raise StorageError("No active session to close.")
                else:
                    selected = self._resolve_selector(selector, sessions)
                if selected.state not in (SessionState.ACTIVE, SessionState.PAUSED):
                    raise StorageError("Only ACTIVE or PAUSED sessions can be closed.")
                selected.durations(timestamp)
                path = self.root / "unfinished" / f"{selected.id}.json"
                return PendingClose(session_id=selected.id, timestamp=timestamp,
                                    saved_record=path.read_bytes())
        except ClockError:
            raise
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not prepare close: {error}") from error

    def commit_close(self, pending: PendingClose, goal_completed: bool, notes: str) -> Session:
        """Archive a complete record before cleanup, only for unchanged input."""
        try:
            if not isinstance(goal_completed, bool) or not isinstance(notes, str):
                raise ValueError("Closing answers require boolean goal completion and string notes.")
            with self._access():
                sessions = self._unfinished_inventory()
                selected = next((session for session in sessions
                                 if session.id == pending.session_id), None)
                path = self.root / "unfinished" / f"{pending.session_id}.json"
                if (selected is None or path.read_bytes() != pending.saved_record
                        or selected.state not in (SessionState.ACTIVE, SessionState.PAUSED)):
                    raise StorageError("Session changed while close input was pending. Run wsm close again.")
                durations = selected.durations(pending.timestamp)
                if selected.state is SessionState.PAUSED:
                    selected.pauses[-1].ended_at = pending.timestamp
                selected.ended_at = pending.timestamp
                selected.goal_completed = goal_completed
                selected.notes = notes
                selected.active_duration_seconds = durations.active_seconds
                selected.paused_duration_seconds = durations.paused_seconds
                selected.total_duration_seconds = durations.total_seconds
                for pause in selected.pauses:
                    pause.duration_seconds = int((pause.ended_at - pause.started_at).total_seconds())
                selected.validate_timing()
                data = selected.to_dict()
                archive = self.root / "sessions" / path.name
                if archive.exists():
                    raise StorageError(f"Archive already exists: {archive}")
                self._write_json(archive, data)
                try:
                    path.unlink()
                except OSError as error:
                    raise StorageError(f"Archive saved at {archive}, but unfinished cleanup failed: {error}") from error
                return selected
        except ClockError:
            raise
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not close session: {error}") from error

    def resume(self, selector: str | None, *, clock: Clock | None = None) -> Session:
        """Validate and close the selected open pause under one store lock."""
        try:
            with self._access():
                sessions = self._unfinished_inventory()
                selected = self._resolve_selector(selector, sessions)
                if selected.state is SessionState.CREATED:
                    raise StorageError("This session has not started. Use wsm start instead.")
                if selected.state is not SessionState.PAUSED:
                    raise StorageError("Only PAUSED sessions can be resumed.")
                active = next((session for session in sessions
                               if session.state is SessionState.ACTIVE), None)
                if active is not None:
                    raise StorageError(f"An ACTIVE session already exists: {active.name}. Pause or close it first.")
                timestamp = capture_time(clock)
                selected.durations(timestamp)
                selected.pauses[-1].ended_at = timestamp
                selected.validate_timing()
                self._write_json(self.root / "unfinished" / f"{selected.id}.json",
                                 selected.to_dict())
                return selected
        except ClockError:
            raise
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not resume session: {error}") from error

    def status(self, *, clock: Clock | None = None) -> StatusSnapshot:
        """Read status without rewriting records or listing selectors."""
        try:
            with self._access():
                sessions = self._unfinished_inventory()
                active = next((session for session in sessions
                               if session.state is SessionState.ACTIVE), None)
                durations = active.durations(capture_time(clock)) if active is not None else None
                return StatusSnapshot(
                    active=active, durations=durations,
                    paused_count=sum(session.state is SessionState.PAUSED for session in sessions),
                    created_count=sum(session.state is SessionState.CREATED for session in sessions),
                )
        except ClockError:
            raise
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not read status: {error}") from error

    def _resolve_selector(self, text: str | None, sessions: list[Session]) -> Session:
        """Resolve against an inventory while the caller holds store access."""
        try:
            if not isinstance(text, str) or not text.isascii() or not text.isdecimal():
                raise ValueError("A positive numeric selector is required.")
            number = str(int(text))
            if int(number) <= 0:
                raise ValueError("A positive numeric selector is required.")
            mapping = self._read_json(self.root / "selectors.json")
            if not isinstance(mapping, dict):
                raise ValueError("The selector mapping must be an object.")
            identities = set()
            for key, value in mapping.items():
                if not key.isascii() or not key.isdecimal() or int(key) <= 0 or str(int(key)) != key:
                    raise ValueError("Invalid number in selector mapping.")
                if not isinstance(value, str):
                    raise ValueError("Invalid identity in selector mapping.")
                identity = UUID(value)
                if identity.version != 4 or str(identity) != value or value in identities:
                    raise ValueError("Invalid or duplicate identity in selector mapping.")
                identities.add(value)
            if number not in mapping:
                raise ValueError(f"Selector {number} is unavailable.")
            for session in sessions:
                if str(session.id) == mapping[number]:
                    return session
            raise ValueError(f"Selector {number} points to a missing or CLOSED session.")
        except StorageError as error:
            raise StorageError(f"{error} Run wsm sessions.") from error
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not resolve selector: {error} Run wsm sessions.") from error

    @staticmethod
    def _load_session(path: Path) -> Session:
        try:
            session = Session.from_dict(SessionStore._read_json(path))
            session.validate_timing()
            if path.name != f"{session.id}.json":
                raise ValueError("Session identity does not match its filename.")
            if session.state is SessionState.CLOSED:
                raise ValueError("A CLOSED record cannot be in unfinished storage.")
            return session
        except (OSError, ValueError) as error:
            raise StorageError(f"Could not load {path}: {error}") from error

    @staticmethod
    def _read_json(path: Path) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
        except (OSError, ValueError, RecursionError) as error:
            raise StorageError(f"Could not read {path}: {error}") from error

    def _unfinished_inventory(self) -> list[Session]:
        """Read one inventory while the caller holds exclusive store access."""
        sessions = []
        for path in (self.root / "unfinished").iterdir():
            if path.suffix != ".json":
                continue
            archive = self.root / "sessions" / path.name
            if archive.exists():
                self._recover_close(path, archive)
                continue
            sessions.append(self._load_session(path))
        active = [session for session in sessions if session.state is SessionState.ACTIVE]
        if len(active) > 1:
            filenames = ", ".join(f"{session.id}.json" for session in active)
            raise StorageError(f"Store contains multiple ACTIVE sessions: {filenames}")
        return sessions

    def _recover_close(self, path: Path, archive: Path) -> None:
        """Verify a duplicate under the inventory lock before removing it."""
        try:
            unfinished = self._load_session(path)
            closed = Session.from_dict(self._read_json(archive))
            closed.validate_timing()
            if (unfinished.state not in (SessionState.ACTIVE, SessionState.PAUSED)
                    or closed.state is not SessionState.CLOSED
                    or archive.name != f"{closed.id}.json"):
                raise ValueError("Expected an ACTIVE or PAUSED copy and its CLOSED archive.")
            prior = unfinished.to_dict()
            completion = closed.to_dict()
            # Closing adds only session closing fields and pause durations.
            # Compare every original field, including the complete pause history.
            completion["pauses"] = [
                {key: value for key, value in pause.items() if key != "duration_seconds"}
                for pause in completion["pauses"]
            ]
            if unfinished.state is SessionState.PAUSED:
                if (not completion["pauses"]
                        or completion["pauses"][-1]["ended_at"] != completion["ended_at"]):
                    raise ValueError("The open pause must end at the CLOSED session end.")
                # Undo only the permitted new event for comparison; all prior
                # pause starts, reasons and ends must still agree exactly.
                completion["pauses"][-1]["ended_at"] = None
            if any(completion[key] != value for key, value in prior.items()):
                raise ValueError("Archive does not complete the saved session history.")
        except (StorageError, ValueError) as error:
            raise StorageError(f"Conflicting session copies: {path} and {archive}: {error}") from error
        try:
            path.unlink()
        except OSError as error:
            raise StorageError(f"Archive preserved at {archive}, but interrupted-close cleanup failed for {path}: {error}") from error

    def _ensure_directories(self) -> None:
        for name in ("unfinished", "sessions"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _access(self) -> Iterator[None]:
        """Coordinate commands; closing the descriptor also releases the lock."""
        self._ensure_directories()
        with (self.root / ".lock").open("a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    @staticmethod
    def _write_json(path: Path, data: object) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".wsm-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
