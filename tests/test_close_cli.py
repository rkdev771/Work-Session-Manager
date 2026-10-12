"""Close prompts, failures, and independent CLI executions."""

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
from wsm.session import Session
from wsm.storage import SessionStore


FIRST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


class CloseCliTests(unittest.TestCase):
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
        self.path = self.root / "unfinished" / f"{FIRST_ID}.json"
        self.archive = self.root / "sessions" / self.path.name

    def run_cli(self, arguments, clock=None):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main(arguments, clock=clock)
        return result, output.getvalue(), errors.getvalue()

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def pause(self, seconds=10):
        self.store.commit_pause(
            self.store.capture_pause(clock=lambda: START + timedelta(seconds=seconds)), "Break")

    def test_paused_close_retries_retain_timestamp_and_include_open_pause(self):
        self.pause()
        events, prompts = [], []
        answers = iter(["bad", "Y", "partial", "NO", ""])
        def clock():
            events.append("clock")
            return START + timedelta(seconds=60, microseconds=999999)
        def answer(prompt):
            events.append("input")
            prompts.append(prompt)
            return next(answers)
        with patch("builtins.input", side_effect=answer):
            result, output, errors = self.run_cli(["close", "1"], clock)
        self.assertEqual((result, errors), (0, ""))
        self.assertEqual(events, ["clock"] + ["input"] * 5)
        self.assertEqual(prompts, ["Close this session? [y/n]: "] * 2
                         + ["Did you accomplish your goal? [y/n]: "] * 2 + ["Notes (optional): "])
        self.assertIn("Closed session: Work", output)
        self.assertIn("Goal completed: no", output)
        self.assertIn("Active: 00:00:10", output)
        self.assertIn("Paused: 00:00:50", output)
        self.assertIn("Total elapsed: 00:01:00", output)
        saved = Session.from_dict(json.loads(self.archive.read_text()))
        saved.validate_timing()
        self.assertEqual(saved.ended_at, START + timedelta(seconds=60))
        self.assertEqual(saved.pauses[-1].ended_at, saved.ended_at)
        self.assertFalse(saved.goal_completed)
        self.assertEqual(saved.notes, "")

    def test_paused_every_prompt_cancellation_and_refusal_preserve_open_pause(self):
        self.pause()
        before = self.files()
        for interruption in (EOFError, KeyboardInterrupt):
            for prefix in ([], ["bad"], ["yes"], ["yes", "bad"], ["yes", "no"]):
                with self.subTest(interruption=interruption, prefix=prefix):
                    with patch("builtins.input", side_effect=prefix + [interruption()]):
                        result, output, errors = self.run_cli(["close", "1"], lambda: START + timedelta(seconds=60))
                    self.assertEqual(result, 1)
                    self.assertIn("cancelled", errors)
                    self.assertNotIn("Closed session", output)
                    self.assertEqual(self.files(), before)
        for answer in ("n", " NO "):
            with patch("builtins.input", side_effect=[answer]):
                result, output, errors = self.run_cli(["close", "1"], lambda: START + timedelta(seconds=60))
            self.assertEqual((result, errors), (0, ""))
            self.assertIn("cancelled", output)
            self.assertEqual(self.files(), before)

    def test_paused_clock_and_stored_timing_errors_fail_before_prompts(self):
        self.pause()
        before = self.files()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            result, output, errors = self.run_cli(["close", "1"], lambda: START + timedelta(seconds=9))
        self.assertEqual((result, output), (1, ""))
        self.assertIn("system clock appears inconsistent", errors)
        self.assertEqual(self.files(), before)
        data = json.loads(self.path.read_text())
        data["pauses"][-1]["started_at"] = "2026-10-11T19:00:10.000001+00:00"
        self.path.write_text(json.dumps(data))
        before = self.files()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            result, output, errors = self.run_cli(["close", "1"], lambda: START + timedelta(seconds=60))
        self.assertEqual((result, output), (1, ""))
        self.assertIn("Invalid stored timing", errors)
        self.assertNotIn("system clock", errors)
        self.assertEqual(self.files(), before)

    def test_paused_save_and_cleanup_failures_do_not_report_success(self):
        self.pause()
        before = self.files()
        with patch("os.replace", side_effect=OSError("Disk failure")):
            with patch("builtins.input", side_effect=["y", "y", "Done"]):
                result, output, errors = self.run_cli(["close", "1"], lambda: START + timedelta(seconds=60))
        self.assertEqual(result, 1)
        self.assertIn("Disk failure", errors)
        self.assertNotIn("Closed session", output)
        self.assertEqual(self.files(), before)
        unlink = Path.unlink
        def fail_cleanup(path, *args, **kwargs):
            if path == self.path:
                raise OSError("Cleanup failure")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", new=fail_cleanup):
            with patch("builtins.input", side_effect=["y", "y", "Done"]):
                result, output, errors = self.run_cli(["close", "1"], lambda: START + timedelta(seconds=60))
            self.assertEqual(result, 1)
            self.assertIn("Archive saved", errors)
            self.assertNotIn("Closed session", output)
        self.assertEqual(self.path.read_bytes(), before[f"unfinished/{FIRST_ID}.json"])
        Session.from_dict(json.loads(self.archive.read_text())).validate_timing()

    def test_paused_close_rejects_resume_during_prompt_in_another_process(self):
        self.pause()
        answers = iter(["yes", "yes", "Done"])
        changed = []
        def answer(prompt):
            if not changed:
                resumed = self.run_process(["resume", "1"], 70)
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                changed.append(self.files())
            return next(answers)
        with patch("builtins.input", side_effect=answer):
            result, output, errors = self.run_cli(["close", "1"], lambda: START + timedelta(seconds=60))
        self.assertEqual(result, 1)
        self.assertIn("changed while close input", errors)
        self.assertNotIn("Closed session", output)
        self.assertEqual(self.files(), changed[0])

    def test_independent_paused_close_and_recovery_preserve_other_active_work(self):
        self.pause()
        original = self.path.read_bytes()
        created = self.run_process(["create"], answers="Zoology\nRead\n")
        self.assertEqual(created.returncode, 0, created.stderr)
        listed = self.run_process(["sessions"])
        self.assertEqual(listed.returncode, 0, listed.stderr)
        started = self.run_process(["start", "2"], 20)
        self.assertEqual(started.returncode, 0, started.stderr)
        other = self.store.resolve_selector("2")
        other_path = self.root / "unfinished" / f"{other.id}.json"
        other_bytes = other_path.read_bytes()
        closed = self.run_process(["close", "1"], 60, "Y\nyEs\nCompleted\n")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertIn("Goal completed: yes", closed.stdout)
        self.assertIn("Active: 00:00:10", closed.stdout)
        self.assertIn("Paused: 00:00:50", closed.stdout)
        saved = Session.from_dict(json.loads(self.archive.read_text()))
        saved.validate_timing()
        self.assertTrue(saved.goal_completed)
        self.assertEqual(saved.notes, "Completed")
        archive = self.archive.read_bytes()
        self.path.write_bytes(original)
        recovered = self.run_process(["status"], 70)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("Title: Zoology", recovered.stdout)
        self.assertIn("Active: 00:00:50", recovered.stdout)
        self.assertFalse(self.path.exists())
        self.assertEqual(other_path.read_bytes(), other_bytes)
        self.assertEqual(self.archive.read_bytes(), archive)
        for arguments in (["resume", "1"], ["close", "1"]):
            rejected = self.run_process(arguments, 80, "y\nn\nReplacement\n")
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("CLOSED", rejected.stderr)
            self.assertNotIn("Close this session?", rejected.stdout)
        data = json.loads(original)
        data["pauses"][-1]["reason"] = "Changed"
        self.path.write_text(json.dumps(data))
        before = self.files()
        failed = self.run_process(["sessions"])
        self.assertEqual(failed.returncode, 1)
        self.assertIn("Conflicting session copies", failed.stderr)
        self.assertEqual(self.files(), before)

    def test_retries_retain_candidate_and_report_final_durations(self):
        answers = iter(["maybe", " YES ", "partial", "N", ""])
        events = []
        prompts = []
        def clock():
            events.append("clock")
            return START + timedelta(hours=27, microseconds=999999)
        def answer(prompt):
            events.append("input")
            prompts.append(prompt)
            return next(answers)
        with patch("builtins.input", side_effect=answer):
            result, output, errors = self.run_cli(["close", "1"], clock)
        self.assertEqual((result, errors), (0, ""))
        self.assertEqual(events, ["clock"] + ["input"] * 5)
        self.assertEqual(prompts, ["Close this session? [y/n]: "] * 2
                         + ["Did you accomplish your goal? [y/n]: "] * 2 + ["Notes (optional): "])
        self.assertIn("Closed session: Work", output)
        self.assertIn("Goal completed: no", output)
        self.assertIn("Active: 27:00:00", output)
        self.assertIn("Paused: 00:00:00", output)
        self.assertIn("Total elapsed: 27:00:00", output)
        saved = Session.from_dict(json.loads(self.archive.read_text()))
        self.assertEqual(saved.ended_at, START + timedelta(hours=27))
        self.assertFalse(saved.goal_completed)
        self.assertEqual(saved.notes, "")

    def test_confirmation_refusal_saves_nothing(self):
        before = self.files()
        for answer in ("n", " NO "):
            with patch("builtins.input", side_effect=[answer]):
                result, output, errors = self.run_cli(["close"], lambda: START)
            self.assertEqual((result, errors), (0, ""))
            self.assertIn("cancelled", output)
            self.assertNotIn("Closed session", output)
            self.assertEqual(self.files(), before)

    def test_every_prompt_cancellation_discards_all_answers(self):
        before = self.files()
        for interruption in (EOFError, KeyboardInterrupt):
            for prefix in ([], ["bad"], ["yes"], ["yes", "bad"], ["yes", "no"]):
                with self.subTest(interruption=interruption, prefix=prefix):
                    with patch("builtins.input", side_effect=prefix + [interruption()]):
                        result, output, errors = self.run_cli(["close"], lambda: START)
                    self.assertEqual(result, 1)
                    self.assertIn("cancelled", errors)
                    self.assertNotIn("Closed session", output)
                    self.assertEqual(self.files(), before)

    def test_clock_and_stored_timing_errors_fail_before_input(self):
        before = self.files()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            result, output, errors = self.run_cli(["close"], lambda: START - timedelta(seconds=1))
        self.assertEqual((result, output), (1, ""))
        self.assertIn("system clock appears inconsistent", errors)
        self.assertEqual(self.files(), before)
        data = json.loads(self.path.read_text())
        data["started_at"] = "2026-10-11T19:00:00.000001+00:00"
        self.path.write_text(json.dumps(data))
        before = self.files()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            result, output, errors = self.run_cli(["close"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("Invalid stored timing", errors)
        self.assertNotIn("system clock", errors)
        self.assertEqual(self.files(), before)

    def test_invalid_states_and_selectors_do_not_prompt(self):
        for arguments in (["close", "bad"], ["close", "2"]):
            before = self.files()
            with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
                result, output, errors = self.run_cli(arguments, lambda: START)
            self.assertEqual((result, output), (1, ""))
            self.assertIn("Run wsm sessions", errors)
            self.assertEqual(self.files(), before)
        self.store.commit_pause(self.store.capture_pause(clock=lambda: START), "Break")
        before = self.files()
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            result, output, errors = self.run_cli(["close"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("No active session", errors)
        self.assertEqual(self.files(), before)

    def test_close_help_explains_active_default_and_explicit_paused_selection(self):
        process = self.run_process(["close", "--help"])
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("ACTIVE or PAUSED", process.stdout)
        self.assertIn("omit to close the ACTIVE session", " ".join(process.stdout.split()))

    def test_save_and_cleanup_failures_never_report_close_success(self):
        before = self.files()
        with patch("os.replace", side_effect=OSError("Disk failure")):
            with patch("builtins.input", side_effect=["y", "y", "Done"]):
                result, output, errors = self.run_cli(["close"], lambda: START)
        self.assertEqual(result, 1)
        self.assertIn("Disk failure", errors)
        self.assertNotIn("Closed session", output)
        self.assertEqual(self.files(), before)
        unlink = Path.unlink
        def fail_cleanup(path, *args, **kwargs):
            if path == self.path:
                raise OSError("Cleanup failure")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", new=fail_cleanup):
            with patch("builtins.input", side_effect=["y", "y", "Done"]):
                result, output, errors = self.run_cli(["close"], lambda: START)
            self.assertEqual(result, 1)
            self.assertIn("Archive saved", errors)
            self.assertNotIn("Closed session", output)
            result, output, errors = self.run_cli(["status"])
            self.assertEqual(result, 1)
            self.assertIn("cleanup failed", errors)
            self.assertNotIn("No active session", output)
        self.assertTrue(self.archive.exists())
        self.assertEqual(self.path.read_bytes(), before[f"unfinished/{FIRST_ID}.json"])

    def run_process(self, arguments, seconds=0, answers="", cwd=None):
        timestamp = (START + timedelta(seconds=seconds)).isoformat()
        code = ("from datetime import datetime; from wsm.cli import main; "
                f"raise SystemExit(main({arguments!r}, "
                f"clock=lambda: datetime.fromisoformat({timestamp!r})))")
        return subprocess.run([sys.executable, "-c", code], input=answers, text=True,
                              capture_output=True, cwd=cwd, timeout=10)

    def test_prompt_allows_other_process_and_rejects_its_changed_target(self):
        answers = iter(["yes", "yes", "Done"])
        changed = []
        def answer(prompt):
            if not changed:
                listed = self.run_process(["sessions"])
                self.assertEqual(listed.returncode, 0, listed.stderr)
                paused = self.run_process(["pause"], 10, "Break\n")
                self.assertEqual(paused.returncode, 0, paused.stderr)
                changed.append(self.files())
            return next(answers)
        with patch("builtins.input", side_effect=answer):
            result, output, errors = self.run_cli(["close"], lambda: START + timedelta(seconds=20))
        self.assertEqual(result, 1)
        self.assertIn("changed while close input", errors)
        self.assertNotIn("Closed session", output)
        self.assertEqual(self.files(), changed[0])

    def test_independent_close_and_recovery_preserve_saved_result(self):
        original = self.path.read_bytes()
        other_directory = self.home / "elsewhere"
        other_directory.mkdir()
        closed = self.run_process(["close"], 60, "Y\nyEs\nCompleted\n", other_directory)
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertIn("Goal completed: yes", closed.stdout)
        self.assertIn("Active: 00:01:00", closed.stdout)
        saved = Session.from_dict(json.loads(self.archive.read_text()))
        self.assertTrue(saved.goal_completed)
        self.assertEqual(saved.notes, "Completed")
        archive = self.archive.read_bytes()
        self.path.write_bytes(original)
        recovered = self.run_process(["status"], cwd=other_directory)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertIn("No active session", recovered.stdout)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.archive.read_bytes(), archive)
        rejected = self.run_process(["close", "1"], 120, "y\nn\nReplacement\n")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("CLOSED", rejected.stderr)
        self.assertNotIn("Close this session?", rejected.stdout)
        self.assertEqual(self.archive.read_bytes(), archive)
        # A conflicting duplicate is equally visible across executions.
        data = json.loads(original)
        data["goal"] = "Changed"
        self.path.write_text(json.dumps(data))
        before = self.files()
        failed = self.run_process(["sessions"])
        self.assertEqual(failed.returncode, 1)
        self.assertIn("Conflicting session copies", failed.stderr)
        self.assertEqual(self.files(), before)
