"""Tests for the Phase 2 session data structures."""

import unittest
from datetime import datetime, timezone
from uuid import UUID

from wsm.session import Pause, Session, SessionState


SESSION_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
STARTED_AT = datetime(2026, 9, 8, 19, 42, tzinfo=timezone.utc)
PAUSED_AT = datetime(2026, 9, 8, 20, 13, tzinfo=timezone.utc)
RESUMED_AT = datetime(2026, 9, 8, 20, 23, 15, tzinfo=timezone.utc)
CLOSED_AT = datetime(2026, 9, 8, 21, 8, 39, tzinfo=timezone.utc)


def make_session(**changes: object) -> Session:
    """Create a session with shared test values and optional changes."""
    values = {
        "id": SESSION_ID,
        "name": "Calculus Homework",
        "goal": "Complete problems 1-20",
    }
    values.update(changes)
    return Session(**values)


class PauseTests(unittest.TestCase):
    def test_pause_holds_its_timestamps_and_reason(self) -> None:
        pause = Pause(
            started_at=PAUSED_AT,
            ended_at=RESUMED_AT,
            reason="Lunch",
        )

        self.assertEqual(pause.started_at, PAUSED_AT)
        self.assertEqual(pause.ended_at, RESUMED_AT)
        self.assertEqual(pause.reason, "Lunch")


class SessionTests(unittest.TestCase):
    def test_new_session_has_created_state_and_empty_defaults(self) -> None:
        session = make_session()

        self.assertEqual(session.state, SessionState.CREATED)
        self.assertIsNone(session.started_at)
        self.assertIsNone(session.ended_at)
        self.assertEqual(session.pauses, [])
        self.assertIsNone(session.goal_completed)
        self.assertIsNone(session.notes)

    def test_started_session_has_active_state(self) -> None:
        session = make_session(started_at=STARTED_AT)

        self.assertEqual(session.state, SessionState.ACTIVE)

    def test_session_with_open_latest_pause_has_paused_state(self) -> None:
        session = make_session(
            started_at=STARTED_AT,
            pauses=[
                Pause(
                    started_at=PAUSED_AT,
                    ended_at=None,
                    reason="Lunch",
                )
            ],
        )

        self.assertEqual(session.state, SessionState.PAUSED)

    def test_ended_session_has_closed_state(self) -> None:
        session = make_session(started_at=STARTED_AT, ended_at=CLOSED_AT)

        self.assertEqual(session.state, SessionState.CLOSED)

    def test_each_session_gets_its_own_pause_list(self) -> None:
        first_session = make_session()
        second_session = make_session()

        first_session.pauses.append(
            Pause(
                started_at=PAUSED_AT,
                ended_at=None,
                reason="Lunch",
            )
        )

        self.assertEqual(second_session.pauses, [])


if __name__ == "__main__":
    unittest.main()
