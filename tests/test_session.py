"""Tests for the Phase 2 session data structures."""

import json
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_pause_converts_to_and_from_json_compatible_data(self) -> None:
        pause = Pause(
            started_at=PAUSED_AT,
            ended_at=RESUMED_AT,
            reason="Lunch",
            duration_seconds=615,
        )

        json_data = json.loads(json.dumps(pause.to_dict()))

        self.assertEqual(
            json_data,
            {
                "started_at": "2026-09-08T20:13:00+00:00",
                "ended_at": "2026-09-08T20:23:15+00:00",
                "duration_seconds": 615,
                "reason": "Lunch",
            },
        )
        self.assertEqual(Pause.from_dict(json_data), pause)

    def test_pause_validation_rejects_blank_reason(self) -> None:
        pause = Pause(started_at=PAUSED_AT, ended_at=None, reason="   ")

        with self.assertRaisesRegex(ValueError, "Pause reason"):
            pause.to_dict()

    def test_pause_validation_rejects_non_utc_timestamp(self) -> None:
        eastern_offset = timezone(timedelta(hours=-4))
        pause = Pause(
            started_at=datetime(2026, 9, 8, 16, 13, tzinfo=eastern_offset),
            ended_at=None,
            reason="Lunch",
        )

        with self.assertRaisesRegex(ValueError, "timezone-aware UTC"):
            pause.to_dict()

    def test_open_pause_validation_rejects_stored_duration(self) -> None:
        pause = Pause(
            started_at=PAUSED_AT,
            ended_at=None,
            reason="Lunch",
            duration_seconds=10,
        )

        with self.assertRaisesRegex(ValueError, "open pause"):
            pause.to_dict()


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

    def test_created_session_uses_the_amended_json_shape(self) -> None:
        session = make_session()

        data = session.to_dict()

        self.assertEqual(
            data,
            {
                "schema_version": 1,
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "Calculus Homework",
                "goal": "Complete problems 1-20",
                "started_at": None,
                "pauses": [],
            },
        )
        self.assertNotIn("state", data)

    def test_each_state_survives_a_json_round_trip(self) -> None:
        sessions = (
            make_session(),
            make_session(started_at=STARTED_AT),
            make_session(
                started_at=STARTED_AT,
                pauses=[
                    Pause(
                        started_at=PAUSED_AT,
                        ended_at=None,
                        reason="Lunch",
                    )
                ],
            ),
            make_session(
                started_at=STARTED_AT,
                ended_at=CLOSED_AT,
                pauses=[
                    Pause(
                        started_at=PAUSED_AT,
                        ended_at=RESUMED_AT,
                        reason="Lunch",
                        duration_seconds=615,
                    )
                ],
                goal_completed=False,
                notes="Completed problems 1-16.",
                active_duration_seconds=4472,
                paused_duration_seconds=727,
                total_duration_seconds=5199,
            ),
        )

        for session in sessions:
            with self.subTest(state=session.state):
                json_data = json.loads(json.dumps(session.to_dict()))
                restored_session = Session.from_dict(json_data)

                self.assertEqual(restored_session, session)
                self.assertEqual(restored_session.state, session.state)

    def test_closed_session_contains_original_final_json_fields(self) -> None:
        session = make_session(
            started_at=STARTED_AT,
            ended_at=CLOSED_AT,
            goal_completed=False,
            notes="Completed problems 1-16.",
            active_duration_seconds=4472,
            paused_duration_seconds=727,
            total_duration_seconds=5199,
        )

        data = session.to_dict()

        self.assertEqual(data["ended_at"], "2026-09-08T21:08:39+00:00")
        self.assertEqual(data["active_duration_seconds"], 4472)
        self.assertEqual(data["paused_duration_seconds"], 727)
        self.assertEqual(data["total_duration_seconds"], 5199)
        self.assertIs(data["goal_completed"], False)
        self.assertEqual(data["notes"], "Completed problems 1-16.")

    def test_unknown_schema_version_is_rejected(self) -> None:
        data = make_session().to_dict()
        data["schema_version"] = 2

        with self.assertRaisesRegex(ValueError, "Unsupported schema version"):
            Session.from_dict(data)


class SessionValidationTests(unittest.TestCase):
    def test_validation_runs_before_serialization(self) -> None:
        session = make_session(name="   ")

        with self.assertRaisesRegex(ValueError, "Session name"):
            session.to_dict()

    def test_validation_runs_after_deserialization(self) -> None:
        data = make_session().to_dict()
        data["goal"] = ""

        with self.assertRaisesRegex(ValueError, "Session goal"):
            Session.from_dict(data)

    def test_validation_rejects_non_version_four_uuid(self) -> None:
        version_one_id = UUID("550e8400-e29b-11d4-a716-446655440000")
        session = make_session(id=version_one_id)

        with self.assertRaisesRegex(ValueError, "UUIDv4"):
            session.validate()

    def test_created_session_cannot_contain_pauses(self) -> None:
        session = make_session(
            pauses=[Pause(started_at=PAUSED_AT, ended_at=None, reason="Lunch")]
        )

        with self.assertRaisesRegex(ValueError, "created session cannot contain pauses"):
            session.validate()

    def test_only_latest_pause_may_be_open(self) -> None:
        session = make_session(
            started_at=STARTED_AT,
            pauses=[
                Pause(started_at=PAUSED_AT, ended_at=None, reason="Lunch"),
                Pause(started_at=RESUMED_AT, ended_at=None, reason="Phone call"),
            ],
        )

        with self.assertRaisesRegex(ValueError, "most recent pause"):
            session.validate()

    def test_non_closed_session_cannot_contain_closing_data(self) -> None:
        session = make_session(started_at=STARTED_AT, goal_completed=True)

        with self.assertRaisesRegex(ValueError, "cannot contain closing data"):
            session.validate()

    def test_closed_session_requires_all_closing_data(self) -> None:
        session = make_session(started_at=STARTED_AT, ended_at=CLOSED_AT)

        with self.assertRaisesRegex(ValueError, "requires goal_completed"):
            session.validate()

    def test_closed_session_cannot_contain_open_pause(self) -> None:
        session = make_session(
            started_at=STARTED_AT,
            ended_at=CLOSED_AT,
            pauses=[Pause(started_at=PAUSED_AT, ended_at=None, reason="Lunch")],
            goal_completed=False,
            notes="",
            active_duration_seconds=100,
            paused_duration_seconds=10,
            total_duration_seconds=110,
        )

        with self.assertRaisesRegex(ValueError, "closed session cannot contain an open"):
            session.validate()

    def test_duration_must_be_a_non_negative_integer(self) -> None:
        session = make_session(
            started_at=STARTED_AT,
            ended_at=CLOSED_AT,
            goal_completed=True,
            notes="",
            active_duration_seconds=-1,
            paused_duration_seconds=0,
            total_duration_seconds=0,
        )

        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            session.validate()


if __name__ == "__main__":
    unittest.main()
