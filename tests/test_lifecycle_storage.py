"""Start/status persistence and concurrency through SessionStore."""

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


def competing_start(root, selector, ready, begin, results):
    ready.put(True)
    if not begin.wait(10):
        results.put(("timeout", selector))
        return
    try:
        started = SessionStore(Path(root)).start(selector, clock=lambda: START)
        results.put(("started", str(started.id)))
    except StorageError as error:
        results.put(("rejected", str(error)))


def start_during_listing(root, captured, release, results):
    def clock():
        captured.set()
        if not release.wait(10):
            raise RuntimeError("Test did not release supplied clock")
        return START
    try:
        started = SessionStore(Path(root)).start("1", clock=clock)
        results.put(("started", str(started.id)))
    except Exception as error:
        results.put(("error", repr(error)))


def refresh_during_start(root, attempted, completed, results):
    attempted.set()
    try:
        listing = SessionStore(Path(root)).refresh_selectors()
        results.put(("listed", [(number, str(session.id)) for number, session in listing]))
    except Exception as error:
        results.put(("error", repr(error)))
    finally:
        completed.set()


class LifecycleStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "data"
        self.store = SessionStore(self.root)
        self.session = Session(id=FIRST_ID, name="Work", goal="Finish")
        self.store.save_created(self.session)
        self.store.refresh_selectors()

    def snapshot_files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def forbidden_clock(self):
        self.fail("Rejected operations must not capture the clock")

    def write_session_fixture(self, session):
        # Seed lifecycle states whose commands belong to later tickets.
        path = self.root / "unfinished" / f"{session.id}.json"
        path.write_text(json.dumps(session.to_dict()))

    def test_invalid_selections_do_not_capture_time_or_change_files(self) -> None:
        for selector in (None, "", "abc", "0", "-1", "2", "1.0", "١"):
            with self.subTest(selector=selector):
                before = self.snapshot_files()
                with self.assertRaisesRegex(StorageError, "Run wsm sessions"):
                    self.store.start(selector, clock=self.forbidden_clock)
                self.assertEqual(self.snapshot_files(), before)
        for content in (None, "broken", "[]", '{"1": "bad-id"}'):
            with self.subTest(content=content):
                mapping = self.root / "selectors.json"
                if content is None:
                    mapping.unlink(missing_ok=True)
                else:
                    mapping.write_text(content)
                before = self.snapshot_files()
                with self.assertRaisesRegex(StorageError, "Run wsm sessions"):
                    self.store.start("1", clock=self.forbidden_clock)
                self.assertEqual(self.snapshot_files(), before)

    def test_start_rejects_active_and_paused_targets_before_clock_capture(self) -> None:
        for pauses, message in (([], "already started"),
                                ([Pause(started_at=START, ended_at=None, reason="Break")],
                                 "wsm resume")):
            with self.subTest(pauses=pauses):
                session = Session(id=FIRST_ID, name="Work", goal="Finish",
                                  started_at=START, pauses=pauses)
                self.write_session_fixture(session)
                before = self.snapshot_files()
                with self.assertRaisesRegex(StorageError, message):
                    self.store.start("1", clock=self.forbidden_clock)
                self.assertEqual(self.snapshot_files(), before)

    def test_other_active_session_blocks_start_before_clock_capture(self) -> None:
        self.write_session_fixture(Session(id=SECOND_ID, name="Other", goal="Work",
                                           started_at=START))
        before = self.snapshot_files()
        with self.assertRaisesRegex(StorageError, "ACTIVE session already exists"):
            self.store.start("1", clock=self.forbidden_clock)
        self.assertEqual(self.snapshot_files(), before)

    def test_paused_session_does_not_block_start_and_status_counts_it(self) -> None:
        self.write_session_fixture(Session(id=SECOND_ID, name="Paused", goal="Rest",
                                           started_at=START,
                                           pauses=[Pause(started_at=START, ended_at=None, reason="Break")]))
        before = self.snapshot_files()
        snapshot = self.store.status(clock=self.forbidden_clock)
        self.assertIsNone(snapshot.active)
        self.assertIsNone(snapshot.durations)
        self.assertEqual((snapshot.paused_count, snapshot.created_count), (1, 1))
        self.assertEqual(self.snapshot_files(), before)
        self.store.start("1", clock=lambda: START)
        self.assertEqual(self.store.status(clock=lambda: START).paused_count, 1)

    def test_closed_or_missing_selection_is_unavailable_without_clock_capture(self) -> None:
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        path.unlink()
        closed = Session(id=FIRST_ID, name="Work", goal="Finish", started_at=START,
                         ended_at=START, goal_completed=True, notes="",
                         active_duration_seconds=0, paused_duration_seconds=0,
                         total_duration_seconds=0)
        for archived in (False, True):
            with self.subTest(archived=archived):
                if archived:
                    (self.root / "sessions" / path.name).write_text(json.dumps(closed.to_dict()))
                before = self.snapshot_files()
                with self.assertRaisesRegex(StorageError, "missing or CLOSED.*Run wsm sessions"):
                    self.store.start("1", clock=self.forbidden_clock)
                self.assertEqual(self.snapshot_files(), before)

    def test_multiple_active_records_stop_start_and_status_without_changes(self) -> None:
        for identity in (FIRST_ID, SECOND_ID):
            self.write_session_fixture(Session(id=identity, name="Active", goal="Work", started_at=START))
        before = self.snapshot_files()
        for operation in (lambda: self.store.start("1", clock=self.forbidden_clock),
                          lambda: self.store.status(clock=self.forbidden_clock)):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(StorageError, "multiple ACTIVE") as raised:
                    operation()
                for identity in (FIRST_ID, SECOND_ID):
                    self.assertIn(f"{identity}.json", str(raised.exception))
                self.assertEqual(self.snapshot_files(), before)

    def test_start_save_failure_preserves_previous_record_and_mapping(self) -> None:
        before = self.snapshot_files()
        for boundary in ("os.replace", "json.dump"):
            with self.subTest(boundary=boundary):
                with patch(boundary, side_effect=OSError("Disk failure")):
                    with self.assertRaisesRegex(StorageError, "Disk failure"):
                        self.store.start("1", clock=lambda: START)
                self.assertEqual(self.snapshot_files(), before)
                self.assertEqual(self.store.resolve_selector("1").state, SessionState.CREATED)
                self.assertEqual(list((self.root / "unfinished").glob("*.tmp")), [])

    def test_clock_failures_preserve_files_and_are_separate_from_stored_timing(self) -> None:
        before = self.snapshot_files()
        with self.assertRaises(ClockError):
            self.store.start("1", clock=lambda: START.replace(tzinfo=None))
        self.assertEqual(self.snapshot_files(), before)
        self.store.start("1", clock=lambda: START)
        before = self.snapshot_files()
        with self.assertRaisesRegex(ClockError, "system clock appears inconsistent"):
            self.store.status(clock=lambda: START - timedelta(seconds=1))
        self.assertEqual(self.snapshot_files(), before)

    def test_stored_precision_errors_are_identified_at_storage_loading(self) -> None:
        session = Session(id=FIRST_ID, name="Work", goal="Finish",
                          started_at=START.replace(microsecond=1))
        self.write_session_fixture(session)
        before = self.snapshot_files()
        with self.assertRaisesRegex(StorageError, "Invalid stored timing.*whole-second precision"):
            self.store.status(clock=self.forbidden_clock)
        self.assertEqual(self.snapshot_files(), before)

    def test_submicrosecond_storage_errors_are_not_hidden_by_parsing(self) -> None:
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        data = self.session.to_dict()
        data["started_at"] = "2026-10-11T19:00:00.0000001+00:00"
        path.write_text(json.dumps(data))
        before = self.snapshot_files()
        for operation in (self.store.refresh_selectors,
                          lambda: self.store.resolve_selector("1"),
                          lambda: self.store.start("1", clock=self.forbidden_clock),
                          lambda: self.store.status(clock=self.forbidden_clock)):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(StorageError, "Invalid stored timing.*whole-second precision") as raised:
                    operation()
                self.assertIn(path.name, str(raised.exception))
                self.assertEqual(self.snapshot_files(), before)

    def test_status_uses_ended_pauses_and_does_not_require_a_selector_mapping(self) -> None:
        self.write_session_fixture(Session(
            id=FIRST_ID, name="Work", goal="Finish", started_at=START,
            pauses=[Pause(started_at=START + timedelta(minutes=30),
                          ended_at=START + timedelta(minutes=40), reason="Break")],
        ))
        (self.root / "selectors.json").unlink()
        snapshot = self.store.status(clock=lambda: START + timedelta(hours=1, microseconds=999999))
        self.assertEqual(snapshot.durations,
                         Durations(active_seconds=3000, paused_seconds=600, total_seconds=3600))
        self.assertFalse((self.root / "selectors.json").exists())

    def test_overlapping_starts_in_separate_processes_have_one_winner(self) -> None:
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        context = multiprocessing.get_context("spawn")
        for selectors in (("1", "2"), ("1", "1")):
            with self.subTest(selectors=selectors):
                # Each race begins with two CREATED records.
                self.write_session_fixture(self.session)
                self.write_session_fixture(Session(id=SECOND_ID, name="Zoology", goal="Read"))
                ready, results, begin = context.Queue(), context.Queue(), context.Event()
                processes = [context.Process(target=competing_start,
                                             args=(str(self.root), selector, ready, begin, results))
                             for selector in selectors]
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
                    winners = [identity for result, identity in outcomes if result == "started"]
                    self.assertEqual(len(winners), 1, outcomes)
                    self.assertEqual(sum(result == "rejected" for result, _ in outcomes), 1)
                    self.assertEqual(str(self.store.status(clock=lambda: START).active.id), winners[0])
                    states = [self.store.resolve_selector(selector).state for selector in ("1", "2")]
                    self.assertEqual(states.count(SessionState.ACTIVE), 1)
                    self.assertEqual(states.count(SessionState.CREATED), 1)
                finally:
                    self.cleanup_processes(processes)
                    ready.close()
                    results.close()

    def test_listing_during_start_cannot_retarget_the_selected_session(self) -> None:
        # Adding an alphabetically earlier title does not yet change selector 1.
        self.store.save_created(Session(id=SECOND_ID, name="Algebra", goal="Later"))
        context = multiprocessing.get_context("spawn")
        captured, release = context.Event(), context.Event()
        attempted, completed, results = context.Event(), context.Event(), context.Queue()
        starter = context.Process(target=start_during_listing,
                                  args=(str(self.root), captured, release, results))
        listing = context.Process(target=refresh_during_start,
                                  args=(str(self.root), attempted, completed, results))
        try:
            starter.start()
            self.assertTrue(captured.wait(10), "Start did not reach its supplied clock")
            listing.start()
            self.assertTrue(attempted.wait(10))
            # A bounded scheduling wait checks lock exclusion, not elapsed work time.
            self.assertFalse(completed.wait(0.2), "Listing refreshed during an in-progress start")
            release.set()
            outcomes = dict(results.get(timeout=10) for _ in range(2))
            for process in (starter, listing):
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(outcomes.get("started"), str(FIRST_ID), outcomes)
            self.assertEqual(outcomes.get("listed"), [(1, str(SECOND_ID)), (2, str(FIRST_ID))])
            self.assertEqual(self.store.status(clock=lambda: START).active.id, FIRST_ID)
            self.assertEqual(self.store.resolve_selector("1").state, SessionState.CREATED)
        finally:
            release.set()
            self.cleanup_processes([starter, listing])
            results.close()

    @staticmethod
    def cleanup_processes(processes):
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)

    def test_start_persists_event_only_data_and_preserves_selectors(self) -> None:
        mapping = (self.root / "selectors.json").read_bytes()
        started = self.store.start("1", clock=lambda: START.replace(microsecond=999999))
        self.assertEqual(started.state, SessionState.ACTIVE)
        self.assertEqual(started.started_at, START)
        self.assertEqual(SessionStore(self.root).resolve_selector("1"), started)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        data = json.loads((self.root / "unfinished" / f"{FIRST_ID}.json").read_text())
        self.assertEqual(data, {"schema_version": 1, "id": str(FIRST_ID),
                               "name": "Work", "goal": "Finish",
                               "started_at": "2026-10-11T19:00:00+00:00", "pauses": []})

    def test_status_snapshot_survives_restart_and_does_not_refresh_selectors(self) -> None:
        self.store.start("1", clock=lambda: START)
        mapping = (self.root / "selectors.json").read_bytes()
        record = (self.root / "unfinished" / f"{FIRST_ID}.json").read_bytes()
        snapshot = SessionStore(self.root).status(clock=lambda: START + timedelta(hours=1))
        self.assertEqual(snapshot.active.id, FIRST_ID)
        self.assertEqual(snapshot.durations,
                         Durations(active_seconds=3600, paused_seconds=0, total_seconds=3600))
        self.assertEqual((snapshot.paused_count, snapshot.created_count), (0, 0))
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        self.assertEqual((self.root / "unfinished" / f"{FIRST_ID}.json").read_bytes(), record)

    def test_invalid_stored_timing_blocks_all_inventory_operations(self) -> None:
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        mapping = (self.root / "selectors.json").read_bytes()
        damaged = Session(id=FIRST_ID, name="Work", goal="Finish", started_at=START,
                          pauses=[Pause(started_at=START - timedelta(seconds=1),
                                        ended_at=None, reason="Break")])
        path.write_text(json.dumps(damaged.to_dict()))
        record = path.read_bytes()
        def forbidden_clock():
            self.fail("Invalid data must be rejected before clock capture")
        for operation in (
            self.store.refresh_selectors,
            lambda: self.store.resolve_selector("1"),
            lambda: self.store.start("1", clock=forbidden_clock),
            lambda: self.store.status(clock=forbidden_clock),
            lambda: self.store.save_created(Session(id=SECOND_ID, name="New", goal="Save")),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(StorageError, "Invalid stored timing") as raised:
                    operation()
                self.assertIn(path.name, str(raised.exception))
                self.assertEqual(path.read_bytes(), record)
                self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)


if __name__ == "__main__":
    unittest.main()
