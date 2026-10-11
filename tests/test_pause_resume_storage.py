"""Pause/resume behavior through the public store and saved records."""

import json
import multiprocessing
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from unittest.mock import patch

from wsm.clock import ClockError
from wsm.session import Durations, Session, SessionState
from wsm.storage import SessionStore, StorageError


FIRST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
SECOND_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


def competing_transition(root, operation, selector, ready, begin, results):
    ready.put(True)
    if not begin.wait(10):
        results.put(("error", "Test start timeout"))
        return
    try:
        session = getattr(SessionStore(Path(root)), operation)(selector, clock=lambda: START)
        results.put(("saved", str(session.id)))
    except StorageError as error:
        results.put(("rejected", str(error)))
    except Exception as error:
        results.put(("error", repr(error)))


def resume_with_waiting_clock(root, captured, release, results):
    def clock():
        captured.set()
        if not release.wait(10):
            raise RuntimeError("Test clock timeout")
        return START
    try:
        session = SessionStore(Path(root)).resume("1", clock=clock)
        results.put(("resumed", str(session.id)))
    except Exception as error:
        results.put(("error", repr(error)))


def list_sessions(root, results):
    try:
        listing = SessionStore(Path(root)).refresh_selectors()
        results.put(("listed", [(number, str(session.id)) for number, session in listing]))
    except Exception as error:
        results.put(("error", repr(error)))


class PauseResumeStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "data"
        self.store = SessionStore(self.root)
        self.store.save_created(Session(id=FIRST_ID, name="Work", goal="Finish"))
        self.store.refresh_selectors()
        self.store.start("1", clock=lambda: START)

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def pause(self, seconds=0):
        pending = self.store.capture_pause(clock=lambda: START + timedelta(seconds=seconds))
        return self.store.commit_pause(pending, "Break")

    def forbidden_clock(self):
        self.fail("Rejected resume must not capture time")

    def test_capture_and_commit_preserve_candidate_and_event_only_json(self):
        before = self.files()
        pending = self.store.capture_pause(clock=lambda: START + timedelta(minutes=30, microseconds=999999))
        self.assertEqual(self.files(), before)
        paused = self.store.commit_pause(pending, " Lunch ")
        self.assertEqual(paused.id, FIRST_ID)
        self.assertEqual(paused.state, SessionState.PAUSED)
        self.assertEqual(paused.pauses[0].started_at, START + timedelta(minutes=30))
        self.assertEqual(paused.pauses[0].reason, "Lunch")
        self.assertIsNone(paused.pauses[0].ended_at)
        self.assertEqual(paused.durations(START + timedelta(hours=1)),
                         Durations(active_seconds=1800, paused_seconds=1800, total_seconds=3600))
        self.assertEqual(paused.durations(START + timedelta(hours=2)).active_seconds, 1800)
        data = json.loads((self.root / "unfinished" / f"{FIRST_ID}.json").read_text())
        self.assertEqual(data["pauses"], [{"started_at": "2026-10-11T19:30:00+00:00",
                                           "ended_at": None, "reason": "Lunch"}])
        self.assertEqual((self.root / "selectors.json").read_bytes(), before["selectors.json"])

    def test_resume_then_repeated_pause_accumulates_correct_durations(self):
        pending = self.store.capture_pause(clock=lambda: START + timedelta(minutes=30))
        self.store.commit_pause(pending, "Lunch")
        mapping = (self.root / "selectors.json").read_bytes()
        resumed = SessionStore(self.root).resume("1", clock=lambda: START + timedelta(minutes=40, microseconds=1))
        self.assertEqual(resumed.state, SessionState.ACTIVE)
        self.assertEqual(resumed.pauses[0].ended_at, START + timedelta(minutes=40))
        pending = self.store.capture_pause(clock=lambda: START + timedelta(minutes=50))
        paused = self.store.commit_pause(pending, "Call")
        self.assertEqual(paused.durations(START + timedelta(hours=1)),
                         Durations(active_seconds=2400, paused_seconds=1200, total_seconds=3600))
        resumed = self.store.resume("1", clock=lambda: START + timedelta(hours=1))
        self.assertEqual(resumed.durations(START + timedelta(minutes=70)),
                         Durations(active_seconds=3000, paused_seconds=1200, total_seconds=4200))
        data = json.loads((self.root / "unfinished" / f"{FIRST_ID}.json").read_text())
        self.assertTrue(all(set(pause) == {"started_at", "ended_at", "reason"} for pause in data["pauses"]))
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_switching_allows_multiple_paused_sessions_and_creation_while_active(self):
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        self.pause(10)
        self.store.start("2", clock=lambda: START + timedelta(seconds=20))
        before = self.files()
        with self.assertRaisesRegex(StorageError, "ACTIVE session already exists"):
            self.store.resume("1", clock=self.forbidden_clock)
        self.assertEqual(self.files(), before)
        self.pause(30)
        status = self.store.status(clock=self.forbidden_clock)
        self.assertEqual((status.paused_count, status.created_count), (2, 0))
        self.store.resume("1", clock=lambda: START + timedelta(seconds=40))
        self.assertEqual(self.store.resolve_selector("2").state, SessionState.PAUSED)
        self.assertEqual(self.store.status(clock=lambda: START + timedelta(seconds=50)).durations,
                         Durations(active_seconds=20, paused_seconds=30, total_seconds=50))

    def test_invalid_resume_selections_and_states_preserve_data_before_clock(self):
        before = self.files()
        for selector in (None, "", "bad", "0", "-1", "2", "1.0", "١"):
            with self.subTest(selector=selector):
                with self.assertRaisesRegex(StorageError, "Run wsm sessions"):
                    self.store.resume(selector, clock=self.forbidden_clock)
                self.assertEqual(self.files(), before)
        with self.assertRaisesRegex(StorageError, "Only PAUSED"):
            self.store.resume("1", clock=self.forbidden_clock)
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        before = self.files()
        with self.assertRaisesRegex(StorageError, "has not started.*wsm start"):
            self.store.resume("2", clock=self.forbidden_clock)
        self.assertEqual(self.files(), before)
        path = self.root / "unfinished" / f"{SECOND_ID}.json"
        path.unlink()
        closed = Session(id=SECOND_ID, name="Zoology", goal="Read", started_at=START,
                         ended_at=START, goal_completed=True, notes="",
                         active_duration_seconds=0, paused_duration_seconds=0, total_duration_seconds=0)
        for archive in (False, True):
            if archive:
                (self.root / "sessions" / path.name).write_text(json.dumps(closed.to_dict()))
            before = self.files()
            with self.assertRaisesRegex(StorageError, "missing or CLOSED"):
                self.store.resume("2", clock=self.forbidden_clock)
            self.assertEqual(self.files(), before)

    def test_resume_rejects_missing_or_damaged_mapping_before_clock(self):
        self.pause()
        mapping = self.root / "selectors.json"
        for content in (None, "broken", "[]", '{"1": "bad-id"}'):
            with self.subTest(content=content):
                if content is None:
                    mapping.unlink(missing_ok=True)
                else:
                    mapping.write_text(content)
                before = self.files()
                with self.assertRaisesRegex(StorageError, "Run wsm sessions"):
                    self.store.resume("1", clock=self.forbidden_clock)
                self.assertEqual(self.files(), before)

    def test_pause_needs_active_but_does_not_need_selectors(self):
        (self.root / "selectors.json").unlink()
        self.pause()
        self.assertFalse((self.root / "selectors.json").exists())
        before = self.files()
        with self.assertRaisesRegex(StorageError, "No active session"):
            self.store.capture_pause(clock=lambda: START)
        self.assertEqual(self.files(), before)

    def test_blank_reason_can_retry_same_pending_candidate_without_changes(self):
        pending = self.store.capture_pause(clock=lambda: START)
        before = self.files()
        for reason in (None, "", " \t "):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(StorageError, "Pause reason"):
                    self.store.commit_pause(pending, reason)
                self.assertEqual(self.files(), before)
        self.store.commit_pause(pending, "Valid")
        self.assertEqual(self.store.resolve_selector("1").pauses[0].started_at, START)

    def test_equal_timestamps_are_valid_for_repeated_transitions(self):
        self.pause()
        self.store.resume("1", clock=lambda: START)
        self.pause()
        session = self.store.resume("1", clock=lambda: START)
        self.assertEqual(session.durations(START), Durations(active_seconds=0, paused_seconds=0, total_seconds=0))
        self.assertEqual(len(session.pauses), 2)

    def test_backward_pause_and_resume_clocks_preserve_files(self):
        for clock in (lambda: START - timedelta(seconds=1), lambda: START.replace(tzinfo=None)):
            before = self.files()
            with self.assertRaises(ClockError):
                self.store.capture_pause(clock=clock)
            self.assertEqual(self.files(), before)
        self.pause(10)
        before = self.files()
        with self.assertRaisesRegex(ClockError, "system clock appears inconsistent"):
            self.store.resume("1", clock=lambda: START + timedelta(seconds=9))
        self.assertEqual(self.files(), before)
        with self.assertRaises(ClockError):
            self.store.resume("1", clock=lambda: START.replace(tzinfo=None))
        self.assertEqual(self.files(), before)
        self.store.resume("1", clock=lambda: START + timedelta(seconds=20))
        before = self.files()
        with self.assertRaisesRegex(ClockError, "system clock appears inconsistent"):
            self.store.capture_pause(clock=lambda: START + timedelta(seconds=19))
        self.assertEqual(self.files(), before)

    def test_failed_pause_and_resume_writes_preserve_records_and_selectors(self):
        pending = self.store.capture_pause(clock=lambda: START)
        for boundary in ("json.dump", "os.replace"):
            before = self.files()
            with patch(boundary, side_effect=OSError("Disk failure")):
                with self.assertRaisesRegex(StorageError, "Disk failure"):
                    self.store.commit_pause(pending, "Break")
            self.assertEqual(self.files(), before)
        self.store.commit_pause(pending, "Break")
        for boundary in ("json.dump", "os.replace"):
            before = self.files()
            with patch(boundary, side_effect=OSError("Disk failure")):
                with self.assertRaisesRegex(StorageError, "Disk failure"):
                    self.store.resume("1", clock=lambda: START)
            self.assertEqual(self.files(), before)
        self.assertEqual(list((self.root / "unfinished").glob("*.tmp")), [])

    def test_pending_pause_rejects_changes_even_when_target_is_active_again(self):
        pending = self.store.capture_pause(clock=lambda: START)
        self.pause()
        self.store.resume("1", clock=lambda: START)
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while pause input was pending"):
            self.store.commit_pause(pending, "Stale")
        self.assertEqual(self.files(), before)

    def test_pending_pause_rejects_changed_bytes_or_missing_record(self):
        pending = self.store.capture_pause(clock=lambda: START)
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        path.write_text(path.read_text() + "\n")
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while pause input was pending"):
            self.store.commit_pause(pending, "Stale")
        self.assertEqual(self.files(), before)
        path.unlink()
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while pause input was pending"):
            self.store.commit_pause(pending, "Missing")
        self.assertEqual(self.files(), before)

    def test_listing_during_pending_pause_preserves_original_uuid(self):
        pending = self.store.capture_pause(clock=lambda: START)
        self.store.save_created(Session(id=SECOND_ID, name="Algebra", goal="Read"))
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        self.assertEqual(self.store.commit_pause(pending, "Break").id, FIRST_ID)
        self.assertEqual(self.store.resolve_selector("1").id, SECOND_ID)
        self.assertEqual(self.store.resolve_selector("2").state, SessionState.PAUSED)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_bad_inventory_stops_pause_and_resume_without_overwriting_data(self):
        pending = self.store.capture_pause(clock=lambda: START)
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        original = path.read_bytes()
        data = json.loads(original)
        data["started_at"] = "2026-10-11T19:00:00.000001+00:00"
        for content, message in ((json.dumps(data), "Invalid stored timing"), ("broken", "Could not read")):
            path.write_text(content)
            before = self.files()
            for operation in (lambda: self.store.capture_pause(clock=lambda: START),
                              lambda: self.store.commit_pause(pending, "Break"),
                              lambda: self.store.resume("1", clock=self.forbidden_clock)):
                with self.subTest(content=content, operation=operation):
                    with self.assertRaisesRegex(StorageError, message) as raised:
                        operation()
                    self.assertIn(path.name, str(raised.exception))
                    self.assertEqual(self.files(), before)
        path.write_bytes(original)
        other = Session(id=SECOND_ID, name="Other", goal="Work", started_at=START)
        (self.root / "unfinished" / f"{SECOND_ID}.json").write_text(json.dumps(other.to_dict()))
        before = self.files()
        for operation in (lambda: self.store.capture_pause(clock=lambda: START),
                          lambda: self.store.commit_pause(pending, "Break"),
                          lambda: self.store.resume("1", clock=self.forbidden_clock)):
            with self.assertRaisesRegex(StorageError, "multiple ACTIVE"):
                operation()
            self.assertEqual(self.files(), before)

    def test_competing_resumes_and_starts_have_one_active_winner(self):
        self.pause()
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        first = (self.root / "unfinished" / f"{FIRST_ID}.json").read_bytes()
        second = (self.root / "unfinished" / f"{SECOND_ID}.json").read_bytes()
        context = multiprocessing.get_context("spawn")
        for operations in ((("resume", "1"), ("start", "2")),
                           (("resume", "1"), ("resume", "1")),
                           (("resume", "1"), ("resume", "2"))):
            with self.subTest(operations=operations):
                (self.root / "unfinished" / f"{FIRST_ID}.json").write_bytes(first)
                (self.root / "unfinished" / f"{SECOND_ID}.json").write_bytes(second)
                if operations[1][0] == "resume" and operations[1][1] == "2":
                    self.store.start("2", clock=lambda: START)
                    self.pause()
                ready, results, begin = context.Queue(), context.Queue(), context.Event()
                processes = [context.Process(target=competing_transition,
                                             args=(str(self.root), operation, selector, ready, begin, results))
                             for operation, selector in operations]
                try:
                    for process in processes:
                        process.start()
                    for _ in processes:
                        ready.get(timeout=10)
                    begin.set()
                    outcomes = [results.get(timeout=10) for _ in processes]
                    for process in processes:
                        process.join(timeout=10)
                        self.assertEqual(process.exitcode, 0)
                    self.assertEqual(sorted(result for result, _ in outcomes), ["rejected", "saved"], outcomes)
                    states = [self.store.resolve_selector(selector).state for selector in ("1", "2")]
                    self.assertEqual(states.count(SessionState.ACTIVE), 1)
                finally:
                    self.cleanup_processes(processes)
                    ready.close()
                    results.close()

    def test_listing_overlapping_resume_cannot_retarget_selected_uuid(self):
        self.pause()
        self.store.save_created(Session(id=SECOND_ID, name="Algebra", goal="Read"))
        context = multiprocessing.get_context("spawn")
        captured, release, results = context.Event(), context.Event(), context.Queue()
        resumer = context.Process(target=resume_with_waiting_clock,
                                  args=(str(self.root), captured, release, results))
        listing = context.Process(target=list_sessions, args=(str(self.root), results))
        try:
            resumer.start()
            self.assertTrue(captured.wait(10))
            listing.start()
            release.set()
            outcomes = dict(results.get(timeout=10) for _ in range(2))
            for process in (resumer, listing):
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(outcomes.get("resumed"), str(FIRST_ID), outcomes)
            self.assertEqual(outcomes.get("listed"), [(1, str(SECOND_ID)), (2, str(FIRST_ID))])
            self.assertEqual(self.store.resolve_selector("2").state, SessionState.ACTIVE)
        finally:
            release.set()
            self.cleanup_processes([resumer, listing])
            results.close()

    @staticmethod
    def cleanup_processes(processes):
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
