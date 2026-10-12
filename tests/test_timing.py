"""Whole-second clock and session timing tests at public boundaries."""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from wsm.clock import ClockError, capture_time
from wsm.session import Durations, Pause, Session, TimingError


START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


def make_session(**changes) -> Session:
    values = dict(id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                  name="Work", goal="Finish", started_at=START)
    values.update(changes)
    return Session(**values)


class ClockTests(unittest.TestCase):
    def test_supplied_clock_is_converted_to_whole_second_utc(self) -> None:
        supplied = datetime(2026, 10, 11, 15, 0, 1, 999999,
                            tzinfo=timezone(timedelta(hours=-4)))
        captured = capture_time(lambda: supplied)
        self.assertEqual(captured.isoformat(), "2026-10-11T19:00:01+00:00")
        self.assertIs(captured.tzinfo, timezone.utc)

    def test_invalid_clock_values_fail_clearly(self) -> None:
        for supplied in (datetime(2026, 10, 11), None, "now"):
            with self.subTest(supplied=supplied):
                with self.assertRaises(ClockError):
                    capture_time(lambda: supplied)


class TimingTests(unittest.TestCase):
    def test_created_session_has_no_duration(self) -> None:
        session = make_session(started_at=None)
        session.validate_timing()
        self.assertIsNone(session.durations())

    def test_multiple_ended_pauses_and_equal_boundaries_are_valid(self) -> None:
        session = make_session(pauses=[
            Pause(started_at=START, ended_at=START, reason="Zero"),
            Pause(started_at=START + timedelta(seconds=10),
                  ended_at=START + timedelta(seconds=20), reason="First"),
            Pause(started_at=START + timedelta(seconds=20),
                  ended_at=START + timedelta(seconds=30), reason="Second"),
        ])
        self.assertEqual(session.durations(START + timedelta(seconds=40)),
                         Durations(active_seconds=20, paused_seconds=20, total_seconds=40))
        open_zero = make_session(pauses=[Pause(started_at=START, ended_at=None, reason="Zero")])
        self.assertEqual(open_zero.durations(START),
                         Durations(active_seconds=0, paused_seconds=0, total_seconds=0))

    def test_stored_fractional_precision_is_rejected_for_every_event(self) -> None:
        session = make_session(
            ended_at=START + timedelta(seconds=30), goal_completed=False, notes="",
            active_duration_seconds=20, paused_duration_seconds=10, total_duration_seconds=30,
            pauses=[Pause(started_at=START + timedelta(seconds=10),
                          ended_at=START + timedelta(seconds=20), reason="Break",
                          duration_seconds=10)],
        )
        for target, field in (("session", "started_at"), ("session", "ended_at"),
                              ("pause", "started_at"), ("pause", "ended_at")):
            with self.subTest(target=target, field=field):
                damaged = Session.from_dict(session.to_dict())
                obj = damaged if target == "session" else damaged.pauses[0]
                setattr(obj, field, getattr(obj, field).replace(microsecond=1))
                with self.assertRaisesRegex(TimingError, "whole-second precision"):
                    damaged.validate_timing()

    def test_submicrosecond_json_timestamps_cannot_be_silently_truncated(self) -> None:
        session = make_session(
            ended_at=START + timedelta(seconds=30), goal_completed=False, notes="",
            active_duration_seconds=20, paused_duration_seconds=10, total_duration_seconds=30,
            pauses=[Pause(started_at=START + timedelta(seconds=10),
                          ended_at=START + timedelta(seconds=20), reason="Break",
                          duration_seconds=10)],
        )
        for target, field in (("session", "started_at"), ("session", "ended_at"),
                              ("pause", "started_at"), ("pause", "ended_at")):
            for fraction in (".0000001", ",0000001", ".0000000001"):
                with self.subTest(target=target, field=field, fraction=fraction):
                    data = session.to_dict()
                    obj = data if target == "session" else data["pauses"][0]
                    obj[field] = obj[field].replace("+00:00", fraction + "+00:00")
                    with self.assertRaisesRegex(ValueError, "Invalid stored timing.*whole-second precision"):
                        Session.from_dict(data).validate_timing()

    def test_calculation_endpoint_must_come_from_whole_second_utc_boundary(self) -> None:
        for endpoint in (None, START.replace(tzinfo=None), START.replace(microsecond=1),
                         START.astimezone(timezone(timedelta(hours=1)))):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ClockError):
                    make_session().durations(endpoint)

    def test_closed_end_cannot_precede_start_or_latest_pause(self) -> None:
        for end, pauses in ((START - timedelta(seconds=1), []),
                            (START, [Pause(started_at=START, ended_at=START + timedelta(seconds=1),
                                           reason="Break", duration_seconds=1)])):
            with self.subTest(end=end):
                session = make_session(ended_at=end, pauses=pauses, goal_completed=False,
                                       notes="", active_duration_seconds=0,
                                       paused_duration_seconds=0, total_duration_seconds=0)
                with self.assertRaisesRegex(TimingError, "latest recorded event"):
                    session.validate_timing()

    def test_zero_length_closed_session_is_valid(self) -> None:
        session = make_session(ended_at=START, goal_completed=False, notes="",
                               active_duration_seconds=0, paused_duration_seconds=0,
                               total_duration_seconds=0,
                               pauses=[Pause(started_at=START, ended_at=START,
                                             reason="Zero", duration_seconds=0)])
        self.assertEqual(session.durations(),
                         Durations(active_seconds=0, paused_seconds=0, total_seconds=0))

    def test_closed_example_uses_its_persisted_end_and_checks_final_counters(self) -> None:
        session = make_session(
            ended_at=START + timedelta(hours=1), goal_completed=True, notes="",
            active_duration_seconds=3000, paused_duration_seconds=600,
            total_duration_seconds=3600,
            pauses=[Pause(started_at=START + timedelta(minutes=30),
                          ended_at=START + timedelta(minutes=40), reason="Lunch",
                          duration_seconds=600)],
        )
        session.validate_timing()
        expected = Durations(active_seconds=3000, paused_seconds=600, total_seconds=3600)
        self.assertEqual(session.durations(), expected)
        self.assertEqual(session.durations(START - timedelta(days=1)), expected)
        for field, value in (("active_duration_seconds", 2999),
                             ("paused_duration_seconds", 601),
                             ("total_duration_seconds", 3601)):
            with self.subTest(field=field):
                damaged = Session.from_dict(session.to_dict())
                setattr(damaged, field, value)
                with self.assertRaisesRegex(TimingError, "inconsistent"):
                    damaged.durations()
        session.pauses[0].duration_seconds = 599
        with self.assertRaisesRegex(TimingError, "inconsistent"):
            session.validate_timing()

    def test_active_without_pauses_counts_only_time_since_start(self) -> None:
        session = make_session()
        self.assertEqual(session.durations(START + timedelta(hours=1)),
                         Durations(active_seconds=3600, paused_seconds=0,
                                   total_seconds=3600))
        self.assertEqual(session.durations(START),
                         Durations(active_seconds=0, paused_seconds=0, total_seconds=0))
        self.assertIsNone(session.active_duration_seconds)

    def test_ended_and_open_pauses_accumulate_without_changing_active_work(self) -> None:
        session = make_session(pauses=[
            Pause(started_at=START + timedelta(minutes=30),
                  ended_at=START + timedelta(minutes=40), reason="Lunch"),
            Pause(started_at=START + timedelta(minutes=50), ended_at=None, reason="Call"),
        ])
        self.assertEqual(session.durations(START + timedelta(hours=1)),
                         Durations(active_seconds=2400, paused_seconds=1200,
                                   total_seconds=3600))
        self.assertEqual(session.durations(START + timedelta(hours=2)),
                         Durations(active_seconds=2400, paused_seconds=4800,
                                   total_seconds=7200))
        self.assertTrue(all(pause.duration_seconds is None for pause in session.pauses))

    def test_stored_pause_chronology_is_validated_before_calculating(self) -> None:
        def pause(start, end):
            return Pause(started_at=START + timedelta(seconds=start),
                         ended_at=None if end is None else START + timedelta(seconds=end),
                         reason="Break")

        for pauses in ([pause(-1, 1)], [pause(2, 1)],
                       [pause(10, 20), pause(19, 30)],
                       [pause(20, 30), pause(10, 15)],
                       [pause(0, None), pause(1, 2)]):
            with self.subTest(pauses=pauses):
                session = make_session(pauses=pauses)
                with self.assertRaisesRegex(TimingError, "Invalid stored timing"):
                    session.validate_timing()
                with self.assertRaises(TimingError):
                    session.durations(START - timedelta(hours=1))

    def test_backward_endpoint_is_compared_with_the_latest_recorded_event(self) -> None:
        for session, endpoint in (
            (make_session(), START - timedelta(seconds=1)),
            (make_session(pauses=[Pause(started_at=START + timedelta(seconds=10),
                                       ended_at=None, reason="Break")]),
             START + timedelta(seconds=9)),
            (make_session(pauses=[Pause(started_at=START + timedelta(seconds=10),
                                       ended_at=START + timedelta(seconds=20), reason="Break")]),
             START + timedelta(seconds=19)),
        ):
            with self.subTest(session=session):
                session.validate_timing()
                with self.assertRaisesRegex(ClockError, "system clock appears inconsistent"):
                    session.durations(endpoint)


if __name__ == "__main__":
    unittest.main()
