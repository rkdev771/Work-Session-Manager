"""Ticket 06 listings through public storage and CLI boundaries."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from unittest.mock import patch

from wsm import cli
from wsm.session import Pause, Session, SessionState
from wsm.storage import SessionStore, StorageError


FIRST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
SECOND_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
THIRD_ID = UUID("550e8400-e29b-41d4-a716-446655440002")
START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


def closed_session(identity=SECOND_ID, name="Algebra"):
    """A valid archive fixture, independent of lifecycle commands."""
    return Session(id=identity, name=name, goal="Done", started_at=START,
                   ended_at=START, goal_completed=True, notes="",
                   active_duration_seconds=0, paused_duration_seconds=0,
                   total_duration_seconds=0)


class ListingStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "data"
        self.store = SessionStore(self.root)
        self.store.refresh_selectors()

    def archive(self, session):
        path = self.root / "sessions" / f"{session.id}.json"
        path.write_text(json.dumps(session.to_dict()), encoding="utf-8")
        return path

    def test_all_appends_unnumbered_archives_with_same_unfinished_mapping(self):
        unfinished = Session(id=FIRST_ID, name="Zoology", goal="Read")
        self.store.save_created(unfinished)
        closed = closed_session(name="Zoology")
        path = self.archive(closed)
        original = path.read_bytes()

        self.assertEqual(self.store.refresh_selectors(), [(1, unfinished)])
        mapping = (self.root / "selectors.json").read_bytes()
        self.assertEqual(self.store.refresh_selectors(include_closed=True),
                         [(1, unfinished), (None, closed)])
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        self.assertEqual(SessionStore(self.root).resolve_selector("1"), unfinished)
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_archives_stop_both_listings_without_replacing_mapping(self):
        self.store.save_created(Session(id=FIRST_ID, name="Work", goal="Read"))
        self.store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        # A successful refresh would now change the mapping.
        self.store.save_created(Session(id=THIRD_ID, name="Algebra", goal="Read"))
        valid = closed_session().to_dict()
        invalid = ["{broken", "null", "[]",
                   json.dumps(Session(id=SECOND_ID, name="Wrong directory", goal="Read").to_dict())]
        for field, value in (("schema_version", 2), ("id", str(THIRD_ID)),
                             ("goal_completed", 1), ("notes", None),
                             ("active_duration_seconds", True),
                             ("total_duration_seconds", 1),
                             ("ended_at", "2026-10-11T18:59:59+00:00"),
                             ("started_at", "2026-10-11T19:00:00.000001+00:00"),
                             ("state", "CLOSED")):
            invalid.append(json.dumps({**valid, field: value}))
        invalid.append(json.dumps({key: value for key, value in valid.items() if key != "notes"}))
        invalid.append(json.dumps(valid).replace('"schema_version": 1',
                                                '"schema_version": 2, "schema_version": 1'))
        path = self.root / "sessions" / f"{SECOND_ID}.json"
        for content in invalid:
            for include_closed in (False, True):
                with self.subTest(content=content, include_closed=include_closed):
                    path.write_text(content, encoding="utf-8")
                    before = path.read_bytes()
                    with self.assertRaisesRegex(StorageError, path.name):
                        self.store.refresh_selectors(include_closed=include_closed)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_empty_and_all_closed_inventories_refresh_to_empty_mapping(self):
        for has_archive in (False, True):
            closed = closed_session()
            if has_archive:
                path = self.archive(closed)
                original = path.read_bytes()
            for include_closed in (False, True):
                with self.subTest(has_archive=has_archive, include_closed=include_closed):
                    (self.root / "selectors.json").write_text(json.dumps({"1": str(SECOND_ID)}))
                    expected = [(None, closed)] if has_archive and include_closed else []
                    self.assertEqual(self.store.refresh_selectors(include_closed=include_closed), expected)
                    self.assertEqual(json.loads((self.root / "selectors.json").read_text()), {})
                    for operation in (lambda: self.store.resolve_selector("1"),
                                      lambda: self.store.start("1", clock=lambda: START),
                                      lambda: self.store.resume("1", clock=lambda: START),
                                      lambda: self.store.capture_close("1", clock=lambda: START)):
                        with self.assertRaisesRegex(StorageError, "Run wsm sessions"):
                            operation()
                    if has_archive:
                        self.assertEqual(path.read_bytes(), original)

    def test_both_forms_compact_close_holes_and_number_new_sessions(self):
        first = Session(id=FIRST_ID, name="Algebra", goal="Read")
        last = Session(id=THIRD_ID, name="Zoology", goal="Read")
        self.store.save_created(first)
        self.store.save_created(last)
        self.store.refresh_selectors()
        self.store.start("1", clock=lambda: START)
        closed = self.store.commit_close(self.store.capture_close(clock=lambda: START), True, "")
        new = Session(id=SECOND_ID, name="Biology", goal="Read")
        self.store.save_created(new)
        with self.assertRaisesRegex(StorageError, "CLOSED"):
            self.store.resolve_selector("1")
        self.assertEqual(self.store.resolve_selector("2"), last)
        expected = [(1, new), (2, last)]
        # Each form starts from the same stale, gapped mapping.
        for include_closed in (False, True):
            (self.root / "selectors.json").write_text(json.dumps({"1": str(FIRST_ID), "2": str(THIRD_ID)}))
            self.assertEqual(self.store.refresh_selectors(include_closed=include_closed),
                             expected + ([(None, closed)] if include_closed else []))
            self.assertEqual(json.loads((self.root / "selectors.json").read_text()),
                             {"1": str(SECOND_ID), "2": str(THIRD_ID)})

    def test_all_sorts_duplicate_unfinished_titles_and_appends_archive_group(self):
        first = Session(id=FIRST_ID, name="Work", goal="First")
        second = Session(id=SECOND_ID, name="Work", goal="Second")
        self.store.save_created(second)
        self.store.save_created(first)
        closed = closed_session(THIRD_ID, "Algebra")
        self.archive(closed)
        self.assertEqual(self.store.refresh_selectors(include_closed=True),
                         [(1, first), (2, second), (None, closed)])

    def test_archive_pause_timing_and_shape_are_validated_when_hidden(self):
        closed = closed_session()
        closed.ended_at = START + timedelta(seconds=20)
        closed.pauses = [Pause(started_at=START + timedelta(seconds=5),
                               ended_at=START + timedelta(seconds=10),
                               reason="Break", duration_seconds=5)]
        closed.active_duration_seconds = 15
        closed.paused_duration_seconds = 5
        closed.total_duration_seconds = 20
        path = self.archive(closed)
        self.assertEqual(self.store.refresh_selectors(include_closed=True), [(None, closed)])
        valid = closed.to_dict()
        for field, value in (("duration_seconds", 4), ("duration_seconds", True),
                             ("ended_at", None), ("reason", " "),
                             ("started_at", "2026-10-11T18:59:59+00:00")):
            for include_closed in (False, True):
                with self.subTest(field=field, value=value, include_closed=include_closed):
                    data = {**valid, "pauses": [{**valid["pauses"][0], field: value}]}
                    path.write_text(json.dumps(data))
                    with self.assertRaisesRegex(StorageError, path.name):
                        self.store.refresh_selectors(include_closed=include_closed)

    def test_listing_recovers_active_and_paused_duplicate_completions(self):
        for paused in (False, True):
            for include_closed in (False, True):
                with self.subTest(paused=paused, include_closed=include_closed):
                    unfinished = Session(id=FIRST_ID, name="Work", goal="Done", started_at=START)
                    closed = closed_session(FIRST_ID, "Work")
                    if paused:
                        unfinished.pauses = [Pause(started_at=START, ended_at=None, reason="Break")]
                        closed.pauses = [Pause(started_at=START, ended_at=START,
                                               reason="Break", duration_seconds=0)]
                    path = self.root / "unfinished" / f"{FIRST_ID}.json"
                    path.write_text(json.dumps(unfinished.to_dict()))
                    archive = self.archive(closed)
                    original = archive.read_bytes()
                    self.assertEqual(self.store.refresh_selectors(include_closed=include_closed),
                                     [(None, closed)] if include_closed else [])
                    self.assertFalse(path.exists())
                    self.assertEqual(archive.read_bytes(), original)
                    self.assertEqual(json.loads((self.root / "selectors.json").read_text()), {})


class ListingCliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        home_patch = patch.dict(os.environ, {"HOME": str(self.home)})
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.root = self.home / ".wsm"
        self.store = SessionStore(self.root)
        self.store.refresh_selectors()

    def run_cli(self, arguments):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main(arguments)
        return result, output.getvalue().splitlines(), errors.getvalue()

    def test_all_flag_help_and_mixed_listing(self):
        parser = cli.build_parser()
        self.assertFalse(parser.parse_args(["sessions"]).all)
        self.assertTrue(parser.parse_args(["sessions", "--all"]).all)
        help_output = io.StringIO()
        with contextlib.redirect_stdout(help_output):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["sessions", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--all", help_output.getvalue())
        self.assertIn("CLOSED", help_output.getvalue())

        self.store.save_created(Session(id=FIRST_ID, name="Zoology", goal="Read"))
        path = self.root / "sessions" / f"{SECOND_ID}.json"
        path.write_text(json.dumps(closed_session(name="Zoology").to_dict()), encoding="utf-8")
        original = path.read_bytes()
        self.assertEqual(self.run_cli(["sessions"]), (0, ["1  Zoology  CREATED"], ""))
        mapping = (self.root / "selectors.json").read_bytes()
        self.assertEqual(self.run_cli(["sessions", "--all"]),
                         (0, ["1  Zoology  CREATED", "Zoology  CLOSED"], ""))
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        self.assertEqual(path.read_bytes(), original)

    def test_empty_and_all_closed_output(self):
        for arguments in (["sessions"], ["sessions", "--all"]):
            self.assertEqual(self.run_cli(arguments), (0, ["No unfinished sessions."], ""))
        path = self.root / "sessions" / f"{SECOND_ID}.json"
        path.write_text(json.dumps(closed_session().to_dict()))
        self.assertEqual(self.run_cli(["sessions"]), (0, ["No unfinished sessions."], ""))
        self.assertEqual(self.run_cli(["sessions", "--all"]),
                         (0, ["No unfinished sessions.", "Algebra  CLOSED"], ""))

    def test_hidden_invalid_archive_reports_clear_file_specific_error(self):
        self.store.save_created(Session(id=FIRST_ID, name="Work", goal="Read"))
        self.store.refresh_selectors()
        path = self.root / "sessions" / f"{SECOND_ID}.json"
        path.write_text("null")
        mapping = (self.root / "selectors.json").read_bytes()
        for arguments in (["sessions"], ["sessions", "--all"]):
            result, output, errors = self.run_cli(arguments)
            self.assertEqual((result, output), (1, []))
            self.assertIn(str(path), errors)
            self.assertNotIn("Traceback", errors)
            self.assertEqual(path.read_text(), "null")
            self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_all_mapping_is_persisted_for_another_process(self):
        self.store.save_created(Session(id=FIRST_ID, name="Work", goal="Read"))
        path = self.root / "sessions" / f"{SECOND_ID}.json"
        path.write_text(json.dumps(closed_session().to_dict()))
        other_cwd = self.home / "another-directory"
        other_cwd.mkdir()
        result = subprocess.run([sys.executable, "-m", "wsm", "sessions", "--all"],
                                text=True, capture_output=True, cwd=other_cwd, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["1  Work  CREATED", "Algebra  CLOSED"])
        mapping = (self.root / "selectors.json").read_bytes()
        result = subprocess.run([sys.executable, "-c",
                                 "from wsm.storage import SessionStore; "
                                 "print(SessionStore().resolve_selector('1').id)"],
                                text=True, capture_output=True, cwd=other_cwd, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(FIRST_ID))
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_all_listing_during_prompts_keeps_pause_and_close_uuid(self):
        for command, paused in (("pause", False), ("close", False), ("close", True)):
            with self.subTest(command=command, paused=paused):
                # Each case has its own store, with an archive in the display.
                self.root = self.home / f"{command}-{paused}" / ".wsm"
                with patch.dict(os.environ, {"HOME": str(self.root.parent)}):
                    store = SessionStore(self.root)
                    store.save_created(Session(id=FIRST_ID, name="Work", goal="Read"))
                    store.refresh_selectors()
                    store.start("1", clock=lambda: START)
                    if paused:
                        store.commit_pause(store.capture_pause(clock=lambda: START), "Break")
                    archive = self.root / "sessions" / f"{THIRD_ID}.json"
                    archive.write_text(json.dumps(closed_session(THIRD_ID).to_dict()))
                    original = archive.read_bytes()
                    # Creation leaves selector 1 bound to Work until the prompt.
                    store.save_created(Session(id=SECOND_ID, name="Biology", goal="Read"))
                    answers = iter(["Break"] if command == "pause" else ["yes", "no", ""])

                    def answer(prompt):
                        result = subprocess.run([sys.executable, "-m", "wsm", "sessions", "--all"],
                                                text=True, capture_output=True, timeout=5)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        state = "PAUSED" if paused else "ACTIVE"
                        self.assertEqual(result.stdout.splitlines(),
                                         ["1  Biology  CREATED", f"2  Work  {state}", "Algebra  CLOSED"])
                        return next(answers)

                    with patch("builtins.input", side_effect=answer):
                        output, errors = io.StringIO(), io.StringIO()
                        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                            arguments = [command, "1"] if command == "close" else [command]
                            result = cli.main(arguments, clock=lambda: START + timedelta(seconds=10))
                    self.assertEqual((result, errors.getvalue()), (0, ""))
                    self.assertEqual(store.resolve_selector("1").id, SECOND_ID)
                    self.assertEqual(archive.read_bytes(), original)
                    self.assertEqual(json.loads((self.root / "selectors.json").read_text()),
                                     {"1": str(SECOND_ID), "2": str(FIRST_ID)})
                    if command == "pause":
                        self.assertEqual(store.resolve_selector("2").state, SessionState.PAUSED)
                    else:
                        with self.assertRaisesRegex(StorageError, "CLOSED"):
                            store.resolve_selector("2")
                        saved = Session.from_dict(json.loads(
                            (self.root / "sessions" / f"{FIRST_ID}.json").read_text()))
                        self.assertEqual(saved.ended_at, START + timedelta(seconds=10))


if __name__ == "__main__":
    unittest.main()
