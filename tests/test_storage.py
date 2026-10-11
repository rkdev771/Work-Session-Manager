"""Persistence tests at the public session-store boundary."""

import tempfile
import json
import multiprocessing
from datetime import datetime, timezone
from contextlib import contextmanager
from unittest.mock import patch
import unittest
from pathlib import Path
from uuid import UUID

from wsm.session import Pause, Session, SessionState
from wsm.storage import SessionStore, StorageError


FIRST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
SECOND_ID = UUID("550e8400-e29b-41d4-a716-446655440001")


def competing_create(root, ready, begin, results, name):
    """Start simultaneous public saves in independent processes."""
    ready.put(True)
    begin.wait(10)
    try:
        SessionStore(Path(root)).save_created(Session(id=FIRST_ID, name=name, goal="Keep identity"))
        results.put(("saved", name))
    except StorageError:
        results.put(("rejected", name))


def create_and_list(root, ready, begin, results, worker):
    """Exercise overlapping inventories and creates without real clock values."""
    ready.put(True)
    begin.wait(10)
    try:
        for index in range(8):
            identity = UUID(f"550e8400-e29b-41d4-a716-{worker * 8 + index:012x}")
            store = SessionStore(Path(root))
            store.save_created(Session(id=identity, name=f"Work {worker}-{index}", goal="Persist"))
            listing = store.refresh_selectors()
            assert any(session.id == identity for _, session in listing)
        results.put(None)
    except Exception as error:
        results.put(repr(error))


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "data"
        self.store = SessionStore(self.root)

    def test_created_session_survives_a_new_store_and_listing(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Solve problems")

        self.store.save_created(session)

        self.assertEqual(SessionStore(self.root).refresh_selectors(), [(1, session)])

    def test_duplicate_titles_sort_by_uuid_and_creation_keeps_old_mapping(self) -> None:
        second = Session(id=SECOND_ID, name="Calculus", goal="Second")
        first = Session(id=FIRST_ID, name="Calculus", goal="First")
        self.store.save_created(second)
        self.assertEqual(self.store.refresh_selectors(), [(1, second)])
        self.store.save_created(first)
        self.assertEqual(SessionStore(self.root).resolve_selector("1"), second)
        with self.assertRaisesRegex(StorageError, "wsm sessions"):
            self.store.resolve_selector("2")
        self.assertEqual(self.store.refresh_selectors(), [(1, first), (2, second)])
        self.assertEqual(self.store.resolve_selector("1"), first)

    def test_listing_rebuilds_missing_or_damaged_mapping(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Solve problems")
        self.store.save_created(session)
        for content in (None, "invalid JSON", "[]", '{"1": "not a UUID"}'):
            with self.subTest(content=content):
                if content is None:
                    (self.root / "selectors.json").unlink(missing_ok=True)
                else:
                    (self.root / "selectors.json").write_text(content)
                with self.assertRaisesRegex(StorageError, "wsm sessions"):
                    self.store.resolve_selector("1")
                self.assertEqual(self.store.refresh_selectors(), [(1, session)])
                self.assertEqual(self.store.resolve_selector("1"), session)

    def test_invalid_or_stale_selectors_never_guess_a_session(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Solve problems")
        self.store.save_created(session)
        self.store.refresh_selectors()
        for selector in (None, "", "abc", "0", "-1", "2", "1.0"):
            with self.subTest(selector=selector):
                with self.assertRaisesRegex(StorageError, "wsm sessions"):
                    self.store.resolve_selector(selector)
        (self.root / "unfinished" / f"{FIRST_ID}.json").unlink()
        with self.assertRaisesRegex(StorageError, "wsm sessions"):
            self.store.resolve_selector("1")

    def test_invalid_session_files_stop_listing_preserving_records_and_mapping(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Solve problems")
        self.store.save_created(session)
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        valid = session.to_dict()
        invalid_contents = ["{broken", "null", "[]", "42"]
        for field, value in (("schema_version", 2), ("schema_version", True),
                             ("id", 42), ("id", str(SECOND_ID)),
                             ("goal", " "), ("pauses", {}), ("pauses", [42]),
                             ("started_at", []), ("state", "CREATED")):
            invalid_contents.append(json.dumps({**valid, field: value}))
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        for content in invalid_contents:
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaisesRegex(StorageError, path.name):
                    self.store.refresh_selectors()
                self.assertEqual(path.read_text(), content)
                self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_saving_existing_identity_never_overwrites_it(self) -> None:
        session = Session(id=FIRST_ID, name="Original", goal="Keep it")
        self.store.save_created(session)
        with self.assertRaisesRegex(StorageError, "already exists"):
            self.store.save_created(Session(id=FIRST_ID, name="Replacement", goal="Overwrite"))
        self.assertEqual(self.store.refresh_selectors(), [(1, session)])

    def test_atomic_replacement_failure_preserves_mapping_and_existing_records(self) -> None:
        original = Session(id=FIRST_ID, name="Original", goal="Keep it")
        self.store.save_created(original)
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        record = (self.root / "unfinished" / f"{FIRST_ID}.json").read_bytes()
        with patch("os.replace", side_effect=OSError("simulated replacement failure")):
            with self.assertRaisesRegex(StorageError, "replacement failure"):
                self.store.refresh_selectors()
            with self.assertRaisesRegex(StorageError, "replacement failure"):
                self.store.save_created(Session(id=SECOND_ID, name="New", goal="Save"))
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        self.assertEqual((self.root / "unfinished" / f"{FIRST_ID}.json").read_bytes(), record)
        self.assertEqual(self.store.resolve_selector("1"), original)
        self.assertEqual(self.store.refresh_selectors(), [(1, original)])

    def test_partial_write_failure_keeps_previous_mapping(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Keep it")
        self.store.save_created(session)
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()

        def fail_during_write(data, stream, **kwargs):
            stream.write('{"incomplete":')
            raise OSError("simulated write failure")

        with patch("json.dump", side_effect=fail_during_write):
            with self.assertRaisesRegex(StorageError, "write failure"):
                self.store.refresh_selectors()
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        self.assertEqual(self.store.resolve_selector("1"), session)

    def test_temporary_file_close_failure_preserves_previous_mapping(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Keep it")
        self.store.save_created(session)
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        temporary_file = tempfile.NamedTemporaryFile

        @contextmanager
        def fail_on_close(**kwargs):
            with temporary_file(**kwargs) as stream:
                yield stream
            raise OSError("simulated close failure")

        with patch("tempfile.NamedTemporaryFile", side_effect=fail_on_close):
            with self.assertRaisesRegex(StorageError, "close failure"):
                self.store.refresh_selectors()
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        self.assertEqual(self.store.resolve_selector("1"), session)

    def test_invalid_inventory_blocks_creation_as_well_as_listing(self) -> None:
        self.store.refresh_selectors()
        path = self.root / "unfinished" / "broken.json"
        path.write_text("null")
        with self.assertRaisesRegex(StorageError, "broken.json"):
            self.store.save_created(Session(id=FIRST_ID, name="New", goal="Save"))
        self.assertEqual(path.read_text(), "null")
        self.assertFalse((self.root / "unfinished" / f"{FIRST_ID}.json").exists())

    def test_conflicting_copies_stop_listing_without_rewriting_either(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Keep it")
        self.store.save_created(session)
        self.store.refresh_selectors()
        archive = self.root / "sessions" / f"{FIRST_ID}.json"
        archive.write_text('{"conflicting": "archive"}')
        with self.assertRaisesRegex(StorageError, "Conflicting"):
            self.store.refresh_selectors()
        self.assertEqual(archive.read_text(), '{"conflicting": "archive"}')

    def test_multiple_active_records_are_reported_with_their_files(self) -> None:
        self.store.refresh_selectors()
        for identity in (FIRST_ID, SECOND_ID):
            session = Session(id=identity, name="Working", goal="One active",
                              started_at=datetime(2026, 10, 11, tzinfo=timezone.utc))
            (self.root / "unfinished" / f"{identity}.json").write_text(json.dumps(session.to_dict()))
        with self.assertRaises(StorageError) as raised:
            self.store.refresh_selectors()
        self.assertIn("multiple ACTIVE", str(raised.exception))
        self.assertIn(f"{FIRST_ID}.json", str(raised.exception))
        self.assertIn(f"{SECOND_ID}.json", str(raised.exception))

    def test_empty_listing_replaces_a_stale_mapping_with_an_empty_object(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Save")
        self.store.save_created(session)
        self.store.refresh_selectors()
        (self.root / "unfinished" / f"{FIRST_ID}.json").unlink()
        self.assertEqual(self.store.refresh_selectors(), [])
        self.assertEqual(json.loads((self.root / "selectors.json").read_text()), {})

    def test_started_sessions_cannot_be_saved_through_created_interface(self) -> None:
        session = Session(id=FIRST_ID, name="Working", goal="Only create",
                          started_at=datetime(2026, 10, 11, tzinfo=timezone.utc))
        with self.assertRaisesRegex(StorageError, "CREATED"):
            self.store.save_created(session)

    def test_listing_includes_unfinished_states_and_creation_allows_active_work(self) -> None:
        self.store.refresh_selectors()
        started = datetime(2026, 10, 11, tzinfo=timezone.utc)
        active = Session(id=FIRST_ID, name="Active", goal="Work", started_at=started)
        paused = Session(id=SECOND_ID, name="Paused", goal="Rest", started_at=started,
                         pauses=[Pause(started_at=started, ended_at=None, reason="Break")])
        for session in (active, paused):
            path = self.root / "unfinished" / f"{session.id}.json"
            path.write_text(json.dumps(session.to_dict()))
        created = Session(id=UUID("550e8400-e29b-41d4-a716-446655440002"),
                          name="Created", goal="Later")
        self.store.save_created(created)
        listing = self.store.refresh_selectors()
        self.assertEqual([(number, session.name, session.state) for number, session in listing],
                         [(1, "Active", SessionState.ACTIVE),
                          (2, "Created", SessionState.CREATED),
                          (3, "Paused", SessionState.PAUSED)])
        self.assertEqual(self.store.resolve_selector("1"), active)

    def test_closed_archive_is_hidden_and_its_stale_selector_is_unavailable(self) -> None:
        self.store.refresh_selectors()
        started = datetime(2026, 10, 11, tzinfo=timezone.utc)
        closed = Session(id=FIRST_ID, name="Archived", goal="Done",
                         started_at=started, ended_at=started, goal_completed=True,
                         notes="", active_duration_seconds=0,
                         paused_duration_seconds=0, total_duration_seconds=0)
        (self.root / "sessions" / f"{FIRST_ID}.json").write_text(json.dumps(closed.to_dict()))
        (self.root / "selectors.json").write_text(json.dumps({"1": str(FIRST_ID)}))
        with self.assertRaisesRegex(StorageError, "wsm sessions"):
            self.store.resolve_selector("1")
        self.assertEqual(self.store.refresh_selectors(), [])

    def test_directory_failure_is_a_clear_storage_error(self) -> None:
        self.root.write_text("A file blocks the data directory")
        for operation in (self.store.refresh_selectors,
                          lambda: self.store.save_created(Session(id=FIRST_ID, name="New", goal="Save"))):
            with self.subTest(operation=operation):
                with self.assertRaises(StorageError):
                    operation()
        self.assertEqual(self.root.read_text(), "A file blocks the data directory")

    def test_ambiguous_json_keys_are_rejected_in_records_and_mapping(self) -> None:
        session = Session(id=FIRST_ID, name="Calculus", goal="Keep it")
        self.store.save_created(session)
        self.store.refresh_selectors()
        mapping = self.root / "selectors.json"
        mapping.write_text(f'{{"1": "{SECOND_ID}", "1": "{FIRST_ID}"}}')
        with self.assertRaisesRegex(StorageError, "wsm sessions"):
            self.store.resolve_selector("1")
        self.store.refresh_selectors()
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        content = json.dumps(session.to_dict()).replace('"schema_version": 1',
                                                       '"schema_version": 2, "schema_version": 1')
        path.write_text(content)
        with self.assertRaisesRegex(StorageError, path.name):
            self.store.refresh_selectors()

    def test_overlapping_creates_with_same_identity_have_one_winner(self) -> None:
        outcomes = self.run_workers(competing_create, 8, lambda index: f"Work {index}")
        winners = [name for result, name in outcomes if result == "saved"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.store.refresh_selectors()[0][1].name, winners[0])

    def test_overlapping_creates_and_listings_preserve_all_records(self) -> None:
        outcomes = self.run_workers(create_and_list, 4, lambda index: index)
        self.assertEqual(outcomes, [None] * 4)
        mapping = json.loads((self.root / "selectors.json").read_text())
        self.assertEqual(set(mapping), {str(number) for number in range(1, 33)})
        self.assertEqual(len(set(mapping.values())), 32)
        self.assertEqual(len(self.store.refresh_selectors()), 32)

    def run_workers(self, worker, count, argument):
        context = multiprocessing.get_context("spawn")
        ready, results = context.Queue(), context.Queue()
        begin = context.Event()
        processes = [context.Process(target=worker, args=(str(self.root), ready, begin, results, argument(index)))
                     for index in range(count)]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                ready.get(timeout=15)
            begin.set()
            outcomes = [results.get(timeout=15) for _ in processes]
            for process in processes:
                process.join(timeout=15)
                self.assertEqual(process.exitcode, 0)
            return outcomes
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            results.close()


if __name__ == "__main__":
    unittest.main()
