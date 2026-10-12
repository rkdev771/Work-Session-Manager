"""Pause/resume prompts and independent command executions."""

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
from unittest.mock import patch
from uuid import UUID

from wsm import cli
from wsm.session import Session, SessionState
from wsm.storage import SessionStore


FIRST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
SECOND_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


class PauseResumeCliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        home_patch = patch.dict(os.environ, {"HOME": str(self.home)})
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.root = self.home / ".wsm"
        self.store = SessionStore(self.root)
        self.store.save_created(Session(id=FIRST_ID, name="Work", goal="Finish"))
        self.store.refresh_selectors()
        self.store.start("1", clock=lambda: START)

    def run_cli(self, arguments, clock=None):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main(arguments, clock=clock)
        return result, output.getvalue(), errors.getvalue()

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def test_pause_retries_keep_pre_prompt_time_then_resume_reports_success(self):
        events = []
        answers = iter(["", "  ", " Lunch "])
        def clock():
            events.append("clock")
            return START + timedelta(minutes=30, microseconds=999999)
        def answer(prompt):
            events.append("input")
            return next(answers)
        mapping = (self.root / "selectors.json").read_bytes()
        with patch("builtins.input", side_effect=answer):
            result, output, errors = self.run_cli(["pause"], clock)
        self.assertEqual((result, errors), (0, ""))
        self.assertIn("Paused session: Work", output)
        self.assertIn("nonwhitespace", output)
        self.assertEqual(events, ["clock", "input", "input", "input"])
        paused = self.store.resolve_selector("1")
        self.assertEqual(paused.pauses[0].reason, "Lunch")
        self.assertEqual(paused.pauses[0].started_at, START + timedelta(minutes=30))
        result, output, errors = self.run_cli(["resume", "1"], lambda: START + timedelta(minutes=40))
        self.assertEqual((result, errors), (0, ""))
        self.assertIn("Resumed session: Work", output)
        self.assertEqual(self.store.resolve_selector("1").state, SessionState.ACTIVE)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def run_process(self, arguments, seconds=0, answers="", cwd=None):
        timestamp = (START + timedelta(seconds=seconds)).isoformat()
        code = ("from datetime import datetime; from wsm.cli import main; "
                f"raise SystemExit(main({arguments!r}, "
                f"clock=lambda: datetime.fromisoformat({timestamp!r})))")
        return subprocess.run([sys.executable, "-c", code], input=answers, text=True,
                              capture_output=True, cwd=cwd, timeout=10)

    def test_cancellation_discards_candidate_and_preserves_all_saved_data(self):
        before = self.files()
        for interruption in (EOFError, KeyboardInterrupt):
            for answers in ([interruption()], ["  ", interruption()]):
                with self.subTest(interruption=interruption, answers=answers):
                    with patch("builtins.input", side_effect=answers):
                        result, output, errors = self.run_cli(["pause"], lambda: START)
                    self.assertEqual(result, 1)
                    self.assertIn("cancelled", errors)
                    self.assertNotIn("Paused session", output)
                    self.assertEqual(self.files(), before)

    def test_no_active_or_backward_clock_fails_before_prompt(self):
        before = self.files()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            result, output, errors = self.run_cli(["pause"], lambda: START - timedelta(seconds=1))
        self.assertEqual((result, output), (1, ""))
        self.assertIn("system clock appears inconsistent", errors)
        self.assertEqual(self.files(), before)
        pending = self.store.capture_pause(clock=lambda: START)
        self.store.commit_pause(pending, "Break")
        before = self.files()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            result, output, errors = self.run_cli(["pause"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("No active session", errors)
        self.assertEqual(self.files(), before)

    def test_resume_invalid_target_and_backward_clock_fail_cleanly(self):
        before = self.files()
        for selector, message in (("1", "Only PAUSED"), ("bad", "Run wsm sessions")):
            result, output, errors = self.run_cli(["resume", selector], lambda: START)
            self.assertEqual((result, output), (1, ""))
            self.assertIn(message, errors)
            self.assertNotIn("Traceback", errors)
            self.assertEqual(self.files(), before)
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START + timedelta(seconds=10)), "Break")
        before = self.files()
        result, output, errors = self.run_cli(["resume", "1"], lambda: START + timedelta(seconds=9))
        self.assertEqual((result, output), (1, ""))
        self.assertIn("system clock appears inconsistent", errors)
        self.assertNotIn("Invalid stored timing", errors)
        self.assertEqual(self.files(), before)
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        data = json.loads(path.read_text())
        data["pauses"][0]["started_at"] = "2026-10-11T18:59:59+00:00"
        path.write_text(json.dumps(data))
        before = self.files()
        for arguments in (["pause"], ["resume", "1"]):
            result, output, errors = self.run_cli(arguments, lambda: START)
            self.assertEqual((result, output), (1, ""))
            self.assertIn("Invalid stored timing", errors)
            self.assertIn(path.name, errors)
            self.assertNotIn("system clock appears inconsistent", errors)
            self.assertNotIn("Traceback", errors)
            self.assertEqual(self.files(), before)

    def test_failed_saves_never_report_pause_or_resume_success(self):
        before = self.files()
        with patch("builtins.input", return_value="Break"):
            with patch("os.replace", side_effect=OSError("Disk failure")):
                result, output, errors = self.run_cli(["pause"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("Disk failure", errors)
        self.assertEqual(self.files(), before)
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START), "Break")
        before = self.files()
        with patch("os.replace", side_effect=OSError("Disk failure")):
            result, output, errors = self.run_cli(["resume", "1"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("Disk failure", errors)
        self.assertEqual(self.files(), before)

    def test_listing_from_another_process_during_prompt_keeps_pause_uuid(self):
        self.store.save_created(Session(id=SECOND_ID, name="Algebra", goal="Read"))
        mapping = None
        def answer(prompt):
            nonlocal mapping
            listed = self.run_process(["sessions"])
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(listed.stdout.splitlines(), ["1  Algebra  CREATED", "2  Work  ACTIVE"])
            mapping = (self.root / "selectors.json").read_bytes()
            return "Break"
        with patch("builtins.input", side_effect=answer):
            result, output, errors = self.run_cli(["pause"], lambda: START)
        self.assertEqual((result, errors), (0, ""))
        self.assertIn("Paused session: Work", output)
        self.assertEqual(self.store.resolve_selector("1").state, SessionState.CREATED)
        self.assertEqual(self.store.resolve_selector("2").state, SessionState.PAUSED)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)

    def test_other_process_can_pause_and_resume_during_prompt_and_stale_save_is_rejected(self):
        newest = None
        def answer(prompt):
            nonlocal newest
            paused = self.run_process(["pause"], seconds=10, answers="Other pause\n")
            self.assertEqual(paused.returncode, 0, paused.stderr)
            resumed = self.run_process(["resume", "1"], seconds=20)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            newest = self.files()
            return "Stale pause"
        with patch("builtins.input", side_effect=answer):
            result, output, errors = self.run_cli(["pause"], lambda: START + timedelta(seconds=5))
        self.assertEqual((result, output), (1, ""))
        self.assertIn("changed while pause input was pending", errors)
        self.assertEqual(self.files(), newest)
        self.assertEqual(self.store.resolve_selector("1").pauses[0].reason, "Other pause")

    def test_independent_commands_switch_work_and_retain_pauses_across_directories(self):
        self.store.save_created(Session(id=SECOND_ID, name="Zoology", goal="Read"))
        self.store.refresh_selectors()
        first, second = self.home / "first", self.home / "second"
        first.mkdir()
        second.mkdir()
        mapping = (self.root / "selectors.json").read_bytes()
        for arguments, seconds, answers, cwd in (
            (["pause"], 1800, " Lunch \n", first),
            (["start", "2"], 1800, "", second),
            (["pause"], 2400, "Switch back\n", first),
            (["status"], 2400, "", second),
            (["resume", "1"], 2400, "", first),
            (["status"], 3600, "", second),
        ):
            result = self.run_process(arguments, seconds, answers, cwd)
            self.assertEqual(result.returncode, 0, result.stderr)
            if arguments == ["status"] and seconds == 2400:
                self.assertEqual(result.stdout.splitlines(), ["No active session.", "PAUSED: 2", "CREATED: 0"])
        self.assertIn("Title: Work", result.stdout)
        self.assertIn("Active: 00:50:00", result.stdout)
        self.assertIn("Paused: 00:10:00", result.stdout)
        self.assertIn("Total elapsed: 01:00:00", result.stdout)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        self.assertFalse((first / ".wsm").exists())
        self.assertFalse((second / ".wsm").exists())
        self.assertEqual(SessionStore(self.root).resolve_selector("2").state, SessionState.PAUSED)

    def test_resume_requires_selector_and_help_describes_selected_pause(self):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as raised:
                cli.main(["resume"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("session", errors.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as raised:
                cli.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Resume a selected paused session", output.getvalue())


if __name__ == "__main__":
    unittest.main()
