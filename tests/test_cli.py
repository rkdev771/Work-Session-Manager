"""Tests for the Phase 1 command-line skeleton."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import UUID
from unittest.mock import Mock, patch

from wsm import cli
from wsm.session import Session
from wsm.storage import SessionStore


class CliTests(unittest.TestCase):
    def test_no_command_displays_help(self) -> None:
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = cli.main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("usage: wsm", output.getvalue())
        self.assertIn("Manage intentional work sessions.", output.getvalue())

    def test_help_lists_all_commands(self) -> None:
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        for command in (
            "create",
            "sessions",
            "status",
            "start",
            "pause",
            "resume",
            "close",
        ):
            self.assertIn(command, output.getvalue())
        self.assertNotIn("finish", output.getvalue())

    def test_each_command_calls_its_handler(self) -> None:
        command_cases = (
            (["create"], "handle_create"),
            (["sessions"], "handle_sessions"),
            (["status"], "handle_status"),
            (["start", "1"], "handle_start"),
            (["pause"], "handle_pause"),
            (["resume", "2"], "handle_resume"),
            (["close"], "handle_close"),
            (["close", "3"], "handle_close"),
        )

        for arguments, handler_name in command_cases:
            with self.subTest(arguments=arguments):
                handler = Mock(return_value=0)

                with patch.object(cli, handler_name, handler):
                    exit_code = cli.main(arguments)

                self.assertEqual(exit_code, 0)
                handler.assert_called_once()

    def test_session_selector_arguments(self) -> None:
        parser = cli.build_parser()

        self.assertEqual(parser.parse_args(["start", "2"]).session, "2")
        self.assertEqual(parser.parse_args(["resume", "3"]).session, "3")
        self.assertEqual(parser.parse_args(["close", "4"]).session, "4")
        self.assertIsNone(parser.parse_args(["close"]).session)


class SavedSessionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        home_patch = patch.dict(os.environ, {"HOME": str(self.home)})
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.root = self.home / ".wsm"

    def test_create_retries_blank_input_and_saves_trimmed_created_record(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", side_effect=["  ", " Calculus ", "", " Solve problems "]):
            with contextlib.redirect_stdout(output):
                result = cli.main(["create"])

        self.assertEqual(result, 0)
        self.assertIn("wsm sessions", output.getvalue())
        listing = SessionStore(self.root).refresh_selectors()
        self.assertEqual(len(listing), 1)
        session = listing[0][1]
        self.assertEqual((session.name, session.goal), ("Calculus", "Solve problems"))
        self.assertEqual(session.id.version, 4)
        data = json.loads((self.root / "unfinished" / f"{session.id}.json").read_text())
        self.assertEqual(data, {
            "schema_version": 1, "id": str(session.id), "name": "Calculus",
            "goal": "Solve problems", "started_at": None, "pauses": [],
        })

    def test_cancellation_at_either_prompt_preserves_existing_data_and_mapping(self) -> None:
        store = SessionStore(self.root)
        existing = Session(id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                           name="Existing", goal="Keep it")
        store.save_created(existing)
        store.refresh_selectors()
        mapping = (self.root / "selectors.json").read_bytes()
        for interruption in (EOFError, KeyboardInterrupt):
            for answers in ([interruption()], ["New title", interruption()]):
                with self.subTest(interruption=interruption, answers=answers):
                    errors = io.StringIO()
                    with patch("builtins.input", side_effect=answers):
                        with contextlib.redirect_stderr(errors):
                            result = cli.main(["create"])
                    self.assertEqual(result, 1)
                    self.assertIn("cancelled", errors.getvalue())
                    self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
                    self.assertEqual(store.refresh_selectors(), [(1, existing)])

    def test_default_listing_displays_selectors_titles_and_states(self) -> None:
        store = SessionStore(self.root)
        store.save_created(Session(id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                                   name="Zoology", goal="Read chapter"))
        store.save_created(Session(id=UUID("550e8400-e29b-41d4-a716-446655440001"),
                                   name="Algebra", goal="Solve equations"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli.main(["sessions"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().splitlines(),
                         ["1  Algebra  CREATED", "2  Zoology  CREATED"])

    def test_empty_listing_reports_no_unfinished_sessions(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli.main(["sessions"])
        self.assertEqual(result, 0)
        self.assertIn("No unfinished sessions.", output.getvalue())
        self.assertEqual(json.loads((self.root / "selectors.json").read_text()), {})

    def test_create_and_listing_persist_across_processes_and_working_directories(self) -> None:
        first_cwd = self.home / "first"
        second_cwd = self.home / "second"
        first_cwd.mkdir()
        second_cwd.mkdir()
        commands = ((first_cwd, ["create"], "Zoology\nRead chapter\n"),
                    (second_cwd, ["create"], "Algebra\nSolve equations\n"),
                    (first_cwd, ["sessions"], ""))
        for cwd, arguments, answers in commands:
            result = subprocess.run([sys.executable, "-m", "wsm", *arguments],
                                    input=answers, text=True, capture_output=True,
                                    cwd=cwd, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ["1  Algebra  CREATED", "2  Zoology  CREATED"])
        mapping = (self.root / "selectors.json").read_bytes()
        result = subprocess.run([sys.executable, "-m", "wsm", "create"],
                                input="Algebra\nAnother goal\n", text=True,
                                capture_output=True, cwd=second_cwd, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        result = subprocess.run([sys.executable, "-c",
                                 "from wsm.storage import SessionStore; "
                                 "s = SessionStore().resolve_selector('1'); "
                                 "print(s.name, s.goal)"], text=True,
                                capture_output=True, cwd=second_cwd, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Algebra Solve equations")
        self.assertFalse((first_cwd / ".wsm").exists())
        self.assertFalse((second_cwd / ".wsm").exists())
        self.assertEqual(len(SessionStore(self.root).refresh_selectors()), 3)

    def test_failed_save_or_listing_never_reports_success(self) -> None:
        for command in ("create", "sessions"):
            with self.subTest(command=command):
                output, errors = io.StringIO(), io.StringIO()
                with patch("builtins.input", side_effect=["New", "Goal"]):
                    with patch("os.replace", side_effect=OSError("Disk failure")):
                        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                            result = cli.main([command])
                self.assertEqual(result, 1)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("Disk failure", errors.getvalue())
                self.assertEqual(SessionStore(self.root).refresh_selectors(), [])

    def test_invalid_record_produces_file_specific_cli_error(self) -> None:
        SessionStore(self.root).refresh_selectors()
        path = self.root / "unfinished" / "broken.json"
        path.write_text("null")
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main(["sessions"])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("broken.json", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_prompt_does_not_prevent_another_process_from_listing(self) -> None:
        def answer(prompt):
            result = subprocess.run([sys.executable, "-m", "wsm", "sessions"],
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "No unfinished sessions.")
            return "Calculus" if prompt.startswith("Title") else "Solve problems"

        with patch("builtins.input", side_effect=answer):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["create"]), 0)
        self.assertEqual(len(SessionStore(self.root).refresh_selectors()), 1)


if __name__ == "__main__":
    unittest.main()
