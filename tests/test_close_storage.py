"""ACTIVE and PAUSED closure through public storage and saved state."""

import json
import multiprocessing
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from wsm.clock import ClockError
from wsm.session import Durations, Pause, Session, SessionState
from wsm.storage import SessionStore, StorageError


FIRST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
SECOND_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


def competing_close(root, ready, begin, results, goal):
    try:
        store = SessionStore(Path(root))
        pending = store.capture_close(clock=lambda: START + timedelta(seconds=60))
        ready.put(True)
        if not begin.wait(10):
            raise RuntimeError("Test start timeout")
        closed = store.commit_close(pending, goal, str(goal))
        results.put(("saved", closed.goal_completed))
    except StorageError as error:
        results.put(("rejected", str(error)))
    except Exception as error:
        results.put(("error", repr(error)))


def competing_recovery(root, ready, begin, results):
    ready.put(True)
    try:
        if not begin.wait(10):
            raise RuntimeError("Test start timeout")
        snapshot = SessionStore(Path(root)).status()
        results.put(("recovered", snapshot.active is None))
    except Exception as error:
        results.put(("error", repr(error)))


def competing_resume_close(root, ready, begin, results, operation):
    try:
        store = SessionStore(Path(root))
        pending = store.capture_close("1", clock=lambda: START + timedelta(seconds=60)) if operation == "close" else None
        ready.put(True)
        if not begin.wait(10):
            raise RuntimeError("Test start timeout")
        if operation == "close":
            store.commit_close(pending, True, "Completed")
        else:
            store.resume("1", clock=lambda: START + timedelta(seconds=50))
        results.put(("saved", operation))
    except StorageError as error:
        results.put(("rejected", str(error)))
    except Exception as error:
        results.put(("error", repr(error)))


def competing_resume_recovery(root, ready, begin, results, operation):
    ready.put(True)
    try:
        if not begin.wait(10):
            raise RuntimeError("Test start timeout")
        store = SessionStore(Path(root))
        if operation == "resume":
            store.resume("1", clock=lambda: START + timedelta(seconds=70))
            results.put(("unexpected resume", operation))
        else:
            store.status()
            results.put(("recovered", operation))
    except StorageError as error:
        results.put(("rejected", str(error)))
    except Exception as error:
        results.put(("error", repr(error)))


class CloseStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "data"
        self.store = SessionStore(self.root)
        self.store.save_created(Session(id=FIRST_ID, name="Work", goal="Finish"))
        self.store.refresh_selectors()
        self.store.start("1", clock=lambda: START)
        self.path = self.root / "unfinished" / f"{FIRST_ID}.json"
        self.archive = self.root / "sessions" / self.path.name

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def capture(self, seconds=3600, selector=None):
        return self.store.capture_close(selector, clock=lambda: START + timedelta(seconds=seconds))

    def pause(self, seconds=10):
        return self.store.commit_pause(
            self.store.capture_pause(clock=lambda: START + timedelta(seconds=seconds)), "Break")

    def test_selected_paused_close_includes_open_pause_and_preserves_active(self):
        self.pause(10)
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        self.store.start("2", clock=lambda: START + timedelta(seconds=20))
        before = self.files()
        pending = self.capture(60, "1")
        self.assertEqual(self.files(), before)
        closed = self.store.commit_close(pending, False, "")
        self.assertEqual(closed.ended_at, START + timedelta(seconds=60))
        self.assertEqual(closed.pauses[-1].ended_at, closed.ended_at)
        self.assertEqual(closed.pauses[-1].duration_seconds, 50)
        self.assertEqual(closed.durations(), Durations(active_seconds=10, paused_seconds=50, total_seconds=60))
        self.assertFalse(closed.goal_completed)
        self.assertEqual(closed.notes, "")
        saved = Session.from_dict(json.loads(self.archive.read_text()))
        saved.validate_timing()
        self.assertEqual(saved.to_dict(), closed.to_dict())
        self.assertFalse(self.path.exists())
        self.assertEqual((self.root / "selectors.json").read_bytes(), before["selectors.json"])
        other_path = self.root / "unfinished" / f"{SECOND_ID}.json"
        self.assertEqual(other_path.read_bytes(), before[f"unfinished/{SECOND_ID}.json"])
        snapshot = self.store.status(clock=lambda: START + timedelta(seconds=70))
        self.assertEqual(snapshot.active.id, SECOND_ID)
        self.assertEqual(snapshot.durations, Durations(active_seconds=50, paused_seconds=0, total_seconds=50))
        with self.assertRaisesRegex(StorageError, "CLOSED"):
            self.store.resolve_selector("1")

    def test_paused_cleanup_failure_preserves_archive_and_recovers_without_new_answers(self):
        self.pause()
        pending = self.capture(60, "1")
        original = self.path.read_bytes()
        mapping = (self.root / "selectors.json").read_bytes()
        unlink = Path.unlink
        def fail_cleanup(path, *args, **kwargs):
            if path == self.path:
                saved = Session.from_dict(json.loads(self.archive.read_text()))
                saved.validate_timing()
                self.assertEqual(saved.pauses[-1].ended_at, saved.ended_at)
                raise OSError("Cleanup failure")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", new=fail_cleanup):
            with self.assertRaisesRegex(StorageError, "Archive saved.*cleanup failed"):
                self.store.commit_close(pending, True, "Original")
            archive = self.archive.read_bytes()
            with self.assertRaisesRegex(StorageError, "interrupted-close cleanup failed"):
                self.store.status()
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(self.archive.read_bytes(), archive)
        with self.assertRaisesRegex(StorageError, "changed while close input"):
            self.store.commit_close(pending, False, "Replacement")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.archive.read_bytes(), archive)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        snapshot = self.store.status()
        self.assertIsNone(snapshot.active)
        self.assertEqual(snapshot.paused_count, 0)
        with self.assertRaisesRegex(StorageError, "CLOSED"):
            self.store.resume("1", clock=lambda: START + timedelta(seconds=70))
        self.assertEqual(self.store.refresh_selectors(), [])

    def test_paused_multiple_and_zero_length_pauses_have_consistent_final_data(self):
        self.pause(0)
        self.store.resume("1", clock=lambda: START)
        self.pause(10)
        self.store.resume("1", clock=lambda: START + timedelta(seconds=20))
        self.pause(30)
        closed = self.store.commit_close(self.capture(30, "1"), True, "Done")
        self.assertEqual(closed.durations(), Durations(active_seconds=20, paused_seconds=10, total_seconds=30))
        self.assertEqual([pause.duration_seconds for pause in closed.pauses], [0, 10, 0])
        self.assertTrue(all(pause.ended_at is not None for pause in closed.pauses))
        self.assertTrue(closed.goal_completed)
        self.assertEqual(closed.notes, "Done")
        Session.from_dict(json.loads(self.archive.read_text())).validate_timing()

    def test_selector_free_close_never_guesses_among_paused_sessions(self):
        self.pause()
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        self.store.start("2", clock=lambda: START + timedelta(seconds=20))
        pending = self.capture(30)
        self.assertEqual(pending.session_id, SECOND_ID)
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START + timedelta(seconds=30)), "Other break")
        before = self.files()
        with self.assertRaisesRegex(StorageError, "No active"):
            self.capture(40)
        self.assertEqual(self.files(), before)

    def test_paused_clock_and_stored_timing_errors_preserve_data(self):
        self.pause()
        before = self.files()
        with self.assertRaisesRegex(ClockError, "system clock appears inconsistent"):
            self.capture(9, "1")
        self.assertEqual(self.files(), before)
        pending = self.capture(60, "1")
        data = json.loads(self.path.read_text())
        data["pauses"][-1]["started_at"] = "2026-10-11T18:59:59+00:00"
        self.path.write_text(json.dumps(data))
        before = self.files()
        for operation in (lambda: self.capture(60, "1"), lambda: self.store.commit_close(pending, True, "")):
            with self.assertRaisesRegex(StorageError, "Invalid stored timing"):
                operation()
            self.assertEqual(self.files(), before)

    def test_paused_archive_write_failures_preserve_open_pause(self):
        self.pause()
        pending = self.capture(60, "1")
        before = self.files()
        for boundary in ("json.dump", "os.replace"):
            with self.subTest(boundary=boundary):
                with patch(boundary, side_effect=OSError("Disk failure")):
                    with self.assertRaisesRegex(StorageError, "Disk failure"):
                        self.store.commit_close(pending, True, "")
                self.assertEqual(self.files(), before)
                self.assertEqual(list((self.root / "sessions").glob("*.tmp")), [])

    def test_paused_pending_close_rejects_format_changes_and_resume(self):
        self.pause()
        pending = self.capture(60, "1")
        original = self.path.read_bytes()
        self.path.write_bytes(original + b"\n")
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while close input"):
            self.store.commit_close(pending, True, "")
        self.assertEqual(self.files(), before)
        self.path.write_bytes(original)
        self.store.resume("1", clock=lambda: START + timedelta(seconds=70))
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while close input"):
            self.store.commit_close(pending, True, "")
        self.assertEqual(self.files(), before)

    def test_paused_conflicting_duplicates_preserve_prior_history_and_changed_copy(self):
        self.pause(10)
        self.store.resume("1", clock=lambda: START + timedelta(seconds=20))
        self.pause(30)
        original = self.path.read_bytes()
        self.store.commit_close(self.capture(60, "1"), True, "")
        archive = self.archive.read_bytes()
        # Every variant is a valid timed record; conflict detection must
        # compare history, rather than rely on timing validation to reject it.
        variants = []
        for index, field, value in ((0, "reason", "Other"), (1, "reason", "Other"),
                                    (0, "started_at", "2026-10-11T19:00:09+00:00"),
                                    (0, "ended_at", "2026-10-11T19:00:21+00:00"),
                                    (1, "started_at", "2026-10-11T19:00:31+00:00")):
            data = json.loads(original)
            data["pauses"][index][field] = value
            variants.append(data)
        resumed = json.loads(original)
        resumed["pauses"][-1]["ended_at"] = "2026-10-11T19:00:50+00:00"
        variants.append(resumed)
        for data in variants:
            with self.subTest(data=data):
                Session.from_dict(data).validate_timing()
                self.path.write_text(json.dumps(data))
                before = self.files()
                for operation in (self.store.status, self.store.refresh_selectors):
                    with self.assertRaisesRegex(StorageError, "Conflicting session copies"):
                        operation()
                    self.assertEqual(self.files(), before)
        self.path.write_bytes(original)
        wrong_end = json.loads(archive)
        wrong_end["pauses"][-1].update(ended_at="2026-10-11T19:00:59+00:00", duration_seconds=29)
        wrong_end.update(active_duration_seconds=21, paused_duration_seconds=39)
        Session.from_dict(wrong_end).validate_timing()
        self.archive.write_text(json.dumps(wrong_end))
        before = self.files()
        with self.assertRaisesRegex(StorageError, "open pause must end"):
            self.store.status()
        self.assertEqual(self.files(), before)

    def test_competing_paused_resume_close_preserve_winners_valid_state(self):
        self.pause()
        outcomes = self.run_competitors(competing_resume_close, [("resume",), ("close",)])
        self.assertEqual(sorted(kind for kind, _ in outcomes), ["rejected", "saved"], outcomes)
        winner = next(value for kind, value in outcomes if kind == "saved")
        if winner == "resume":
            self.assertFalse(self.archive.exists())
            saved = self.store.resolve_selector("1")
            self.assertEqual(saved.state, SessionState.ACTIVE)
            self.assertEqual(saved.pauses[-1].ended_at, START + timedelta(seconds=50))
        else:
            self.assertFalse(self.path.exists())
            saved = Session.from_dict(json.loads(self.archive.read_text()))
            saved.validate_timing()
            self.assertEqual(saved.durations(), Durations(active_seconds=10, paused_seconds=50, total_seconds=60))

    def test_competing_paused_resume_recovery_cannot_resurrect_completed_session(self):
        self.pause()
        original = self.path.read_bytes()
        self.store.commit_close(self.capture(60, "1"), True, "Original")
        archive = self.archive.read_bytes()
        self.path.write_bytes(original)
        outcomes = self.run_competitors(competing_resume_recovery, [("resume",), ("recovery",)])
        self.assertEqual(sorted(kind for kind, _ in outcomes), ["recovered", "rejected"], outcomes)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.archive.read_bytes(), archive)

    def test_competing_recovery_and_resume_preserve_changed_paused_copy(self):
        self.pause()
        original = self.path.read_bytes()
        self.store.commit_close(self.capture(60, "1"), True, "Original")
        data = json.loads(original)
        data["pauses"][-1]["reason"] = "Newer reason"
        self.path.write_text(json.dumps(data))
        before = self.files()
        outcomes = self.run_competitors(competing_resume_recovery, [("resume",), ("recovery",)])
        self.assertEqual([kind for kind, _ in outcomes], ["rejected", "rejected"], outcomes)
        self.assertTrue(all("Conflicting session copies" in detail for _, detail in outcomes))
        self.assertEqual(self.files(), before)

    def test_listing_refresh_does_not_retarget_paused_close(self):
        self.pause()
        pending = self.capture(60, "1")
        self.store.save_created(Session(id=SECOND_ID, name="Algebra", goal="Read"))
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        closed = self.store.commit_close(pending, True, "")
        self.assertEqual(closed.id, FIRST_ID)
        self.assertEqual(self.store.resolve_selector("1").id, SECOND_ID)
        with self.assertRaisesRegex(StorageError, "CLOSED"):
            self.store.resolve_selector("2")
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_close_persists_complete_record_and_preserves_other_selectors(self):
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START + timedelta(minutes=30)), "Lunch")
        self.store.resume("1", clock=lambda: START + timedelta(minutes=40))
        before = self.files()
        pending = self.store.capture_close("1", clock=lambda: START + timedelta(hours=1, microseconds=999999))
        self.assertEqual(self.files(), before)
        closed = self.store.commit_close(pending, False, "")
        self.assertEqual(closed.state, SessionState.CLOSED)
        self.assertEqual(closed.ended_at, START + timedelta(hours=1))
        self.assertEqual(closed.durations(), Durations(active_seconds=3000, paused_seconds=600, total_seconds=3600))
        self.assertEqual(closed.pauses[0].duration_seconds, 600)
        self.assertFalse(closed.goal_completed)
        self.assertEqual(closed.notes, "")
        saved = Session.from_dict(json.loads(self.archive.read_text()))
        saved.validate_timing()
        self.assertEqual(saved.to_dict(), closed.to_dict())
        self.assertFalse(self.path.exists())
        self.assertEqual((self.root / "selectors.json").read_bytes(), before["selectors.json"])
        with self.assertRaisesRegex(StorageError, "CLOSED.*Run wsm sessions"):
            self.store.resolve_selector("1")
        self.assertEqual(self.store.resolve_selector("2").id, SECOND_ID)

    def test_inventory_recovers_verified_archive_before_counting_active(self):
        original = self.path.read_bytes()
        closed = self.store.commit_close(self.capture(), True, "Finished")
        archive_bytes = self.archive.read_bytes()
        self.path.write_bytes(original)
        # Another ACTIVE session is legitimate: the duplicate must not count.
        other = Session(id=SECOND_ID, name="Other", goal="Read", started_at=START)
        (self.root / "unfinished" / f"{SECOND_ID}.json").write_text(json.dumps(other.to_dict()))
        snapshot = SessionStore(self.root).status(clock=lambda: START)
        self.assertEqual(snapshot.active.id, SECOND_ID)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.archive.read_bytes(), archive_bytes)
        self.assertEqual(closed.notes, "Finished")
        with self.assertRaisesRegex(StorageError, "CLOSED"):
            self.store.resolve_selector("1")

    def test_equal_time_and_multiple_pauses_have_final_integer_durations(self):
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START), "Zero")
        self.store.resume("1", clock=lambda: START)
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START + timedelta(seconds=10)), "Break")
        self.store.resume("1", clock=lambda: START + timedelta(seconds=20))
        closed = self.store.commit_close(self.capture(20), True, "Done")
        self.assertEqual(closed.durations(), Durations(active_seconds=10, paused_seconds=10, total_seconds=20))
        self.assertEqual([pause.duration_seconds for pause in closed.pauses], [0, 10])

    def test_close_without_mapping_and_reject_invalid_targets(self):
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        before = self.files()
        for selector in ("", "bad", "0", "-1", "3", "1.0", "١", "2"):
            with self.subTest(selector=selector):
                with self.assertRaises(StorageError):
                    self.capture(selector=selector)
                self.assertEqual(self.files(), before)
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START), "Break")
        before = self.files()
        with self.assertRaisesRegex(StorageError, "No active"):
            self.capture()
        self.assertEqual(self.files(), before)
        self.store.resume("1", clock=lambda: START)
        (self.root / "selectors.json").unlink()
        self.store.commit_close(self.capture(0), True, "")
        before = self.files()
        with self.assertRaisesRegex(StorageError, "No active"):
            self.capture()
        with self.assertRaisesRegex(StorageError, "Run wsm sessions"):
            self.capture(selector="1")
        self.assertEqual(self.files(), before)

    def test_bad_answers_and_backward_clock_preserve_data(self):
        before = self.files()
        for clock in (lambda: START - timedelta(seconds=1), lambda: START.replace(tzinfo=None)):
            with self.assertRaises(ClockError):
                self.store.capture_close(clock=clock)
            self.assertEqual(self.files(), before)
        pending = self.capture()
        for goal, notes in ((1, ""), (None, ""), (False, None)):
            with self.assertRaisesRegex(StorageError, "Closing answers"):
                self.store.commit_close(pending, goal, notes)
            self.assertEqual(self.files(), before)

    def test_pending_close_rejects_changed_bytes_history_or_missing_target(self):
        pending = self.capture()
        original = self.path.read_bytes()
        self.path.write_bytes(original + b"\n")
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while close input"):
            self.store.commit_close(pending, True, "Stale")
        self.assertEqual(self.files(), before)
        self.path.write_bytes(original)
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START), "Break")
        self.store.resume("1", clock=lambda: START)
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while close input"):
            self.store.commit_close(pending, True, "Stale")
        self.assertEqual(self.files(), before)
        self.path.unlink()
        before = self.files()
        with self.assertRaisesRegex(StorageError, "changed while close input"):
            self.store.commit_close(pending, True, "Missing")
        self.assertEqual(self.files(), before)

    def test_listing_does_not_retarget_pending_close(self):
        pending = self.capture()
        self.store.save_created(Session(id=SECOND_ID, name="Algebra", goal="Read"))
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        self.assertEqual(self.store.commit_close(pending, True, "").id, FIRST_ID)
        self.assertEqual(self.store.resolve_selector("1").id, SECOND_ID)
        with self.assertRaisesRegex(StorageError, "CLOSED"):
            self.store.resolve_selector("2")
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_archive_write_failures_preserve_unfinished_and_mapping(self):
        pending = self.capture()
        before = self.files()
        for boundary in ("json.dump", "os.replace"):
            with self.subTest(boundary=boundary):
                with patch(boundary, side_effect=OSError("Disk failure")):
                    with self.assertRaisesRegex(StorageError, "Disk failure"):
                        self.store.commit_close(pending, True, "")
                self.assertEqual(self.files(), before)
                self.assertEqual(list((self.root / "sessions").glob("*.tmp")), [])

    def test_cleanup_failure_preserves_valid_archive_then_recovers(self):
        pending = self.capture()
        original = self.path.read_bytes()
        unlink = Path.unlink
        def fail_cleanup(path, *args, **kwargs):
            if path == self.path:
                self.assertTrue(self.archive.exists())
                saved = Session.from_dict(json.loads(self.archive.read_text()))
                saved.validate_timing()
                raise OSError("Cleanup failure")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", new=fail_cleanup):
            with self.assertRaisesRegex(StorageError, "Archive saved.*cleanup failed"):
                self.store.commit_close(pending, True, "Original result")
            archive_bytes = self.archive.read_bytes()
            self.assertEqual(self.path.read_bytes(), original)
            with self.assertRaisesRegex(StorageError, "interrupted-close cleanup failed"):
                SessionStore(self.root).status()
            self.assertEqual(self.archive.read_bytes(), archive_bytes)
            self.assertEqual(self.path.read_bytes(), original)
        # Pending answers cannot replace the authoritative archive, even when
        # their commit itself discovers and finishes interrupted cleanup.
        with self.assertRaisesRegex(StorageError, "changed while close input"):
            SessionStore(self.root).commit_close(pending, False, "Replacement")
        self.assertEqual(self.archive.read_bytes(), archive_bytes)
        self.assertFalse(self.path.exists())
        self.assertIsNone(self.store.status().active)

    def test_conflicting_duplicates_preserve_both_copies(self):
        original = self.path.read_bytes()
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START + timedelta(seconds=10)), "Break")
        self.store.resume("1", clock=lambda: START + timedelta(seconds=20))
        active = self.path.read_bytes()
        self.store.commit_close(self.capture(30), True, "")
        valid_archive = self.archive.read_bytes()
        variants = []
        for key, value in (("id", str(SECOND_ID)), ("name", "Changed"), ("goal", "Other"),
                           ("started_at", "2026-10-11T18:59:59+00:00"),
                           ("ended_at", "2026-10-11T19:00:19+00:00"),
                           ("total_duration_seconds", 99), ("goal_completed", "yes")):
            data = json.loads(valid_archive)
            data[key] = value
            variants.append(json.dumps(data).encode())
        for change in ("reason", "started_at", "ended_at", "duration_seconds", "extra", "missing"):
            data = json.loads(valid_archive)
            if change == "extra":
                data["pauses"].append(dict(data["pauses"][0]))
            elif change == "missing":
                data["pauses"] = []
                data.update(active_duration_seconds=30, paused_duration_seconds=0)
            else:
                data["pauses"][0][change] = {"reason": "Other", "started_at": "2026-10-11T19:00:09+00:00",
                                              "ended_at": "2026-10-11T19:00:21+00:00", "duration_seconds": 9}[change]
            variants.append(json.dumps(data).encode())
        variants += [b"broken", original]
        for variant in variants:
            with self.subTest(archive=variant):
                self.path.write_bytes(active)
                self.archive.write_bytes(variant)
                before = self.files()
                with self.assertRaisesRegex(StorageError, "Conflicting session copies"):
                    self.store.refresh_selectors()
                self.assertEqual(self.files(), before)

    def test_created_and_unmatched_paused_duplicates_are_not_recovered(self):
        original = self.path.read_bytes()
        self.store.commit_close(self.capture(), True, "")
        for session in (Session(id=FIRST_ID, name="Work", goal="Finish"), Session.from_dict(json.loads(original))):
            if session.started_at is not None:
                session.pauses.append(Pause(started_at=START, ended_at=None, reason="Break"))
            self.path.write_text(json.dumps(session.to_dict()))
            before = self.files()
            with self.assertRaisesRegex(StorageError, "Conflicting"):
                self.store.status()
            self.assertEqual(self.files(), before)

    def test_invalid_inventory_is_distinct_from_clock_error_and_preserved(self):
        pending = self.capture()
        data = json.loads(self.path.read_text())
        data["started_at"] = "2026-10-11T19:00:00.000001+00:00"
        self.path.write_text(json.dumps(data))
        before = self.files()
        for operation in (self.capture, lambda: self.store.commit_close(pending, True, "")):
            with self.assertRaisesRegex(StorageError, "Invalid stored timing"):
                operation()
            self.assertEqual(self.files(), before)

    def run_competitors(self, target, extra_arguments):
        context = multiprocessing.get_context("spawn")
        ready, results, begin = context.Queue(), context.Queue(), context.Event()
        processes = [context.Process(target=target, args=(str(self.root), ready, begin, results, *extra))
                     for extra in extra_arguments]
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
            return outcomes
        finally:
            begin.set()
            for process in processes:
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=10)
            ready.close()
            results.close()

    def test_competing_process_closes_preserve_one_winners_archive(self):
        outcomes = self.run_competitors(competing_close, [(True,), (False,)])
        self.assertEqual(sorted(kind for kind, _ in outcomes), ["rejected", "saved"], outcomes)
        winning_goal = next(value for kind, value in outcomes if kind == "saved")
        closed = Session.from_dict(json.loads(self.archive.read_text()))
        closed.validate_timing()
        self.assertEqual(closed.goal_completed, winning_goal)
        self.assertEqual(closed.notes, str(winning_goal))
        self.assertEqual(closed.durations(), Durations(active_seconds=60, paused_seconds=0, total_seconds=60))
        self.assertFalse(self.path.exists())
        self.assertEqual(list((self.root / "sessions").glob("*.json")), [self.archive])

    def test_competing_recovery_processes_preserve_authoritative_archive(self):
        original = self.path.read_bytes()
        self.store.commit_close(self.capture(), True, "Original")
        archive = self.archive.read_bytes()
        self.path.write_bytes(original)
        outcomes = self.run_competitors(competing_recovery, [(), ()])
        self.assertEqual(outcomes, [("recovered", True), ("recovered", True)])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.archive.read_bytes(), archive)
