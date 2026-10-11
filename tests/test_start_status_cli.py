"""Start/status user flows through main and independent CLI executions."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from wsm import cli
from wsm.session import Pause, Session
from wsm.storage import SessionStore


FIRST_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
SECOND_ID = UUID("550e8400-e29b-41d4-a716-446655440001")
START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


class StartStatusCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        home_patch = patch.dict(os.environ, {"HOME": str(self.home)})
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.root = self.home / ".wsm"
        self.store = SessionStore(self.root)

    def run_cli(self, arguments, clock=None):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main(arguments, clock=clock)
        return result, output.getvalue(), errors.getvalue()

    def save_created(self):
        self.store.save_created(Session(id=FIRST_ID, name="Calculus", goal="Solve problems"))
        self.store.refresh_selectors()

    def test_start_then_status_displays_goal_state_and_large_hour_durations(self) -> None:
        self.save_created()
        result, output, errors = self.run_cli(["start", "1"], lambda: START)
        self.assertEqual((result, errors), (0, ""))
        self.assertIn("Started session: Calculus", output)
        result, output, errors = self.run_cli(["status"],
                                             lambda: START + timedelta(hours=27, minutes=2, seconds=3))
        self.assertEqual((result, errors), (0, ""))
        for text in ("Title: Calculus", "Goal: Solve problems", "State: ACTIVE",
                     "Active: 27:02:03", "Paused: 00:00:00", "Total elapsed: 27:02:03"):
            self.assertIn(text, output)

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def test_create_prompt_time_is_excluded_and_clock_is_not_captured_during_create(self) -> None:
        def forbidden_clock():
            self.fail("Creating must not capture a start timestamp")
        with patch("builtins.input", side_effect=[" Calculus ", " Solve problems "]):
            result, _, errors = self.run_cli(["create"], forbidden_clock)
        self.assertEqual((result, errors), (0, ""))
        session = self.store.refresh_selectors()[0][1]
        self.assertIsNone(session.started_at)
        self.run_cli(["start", "1"], lambda: START + timedelta(days=2))
        result, output, errors = self.run_cli(["status"], lambda: START + timedelta(days=2, seconds=10))
        self.assertEqual((result, errors), (0, ""))
        self.assertIn("Active: 00:00:10", output)

    def test_empty_and_paused_status_reports_counts_without_refreshing_selectors(self) -> None:
        result, output, errors = self.run_cli(["status"])
        self.assertEqual((result, errors), (0, ""))
        self.assertEqual(output.splitlines(), ["No active session.", "PAUSED: 0", "CREATED: 0"])
        self.assertFalse((self.root / "selectors.json").exists())
        self.save_created()
        paused = Session(id=SECOND_ID, name="Paused", goal="Rest", started_at=START,
                         pauses=[Pause(started_at=START, ended_at=None, reason="Break")])
        (self.root / "unfinished" / f"{SECOND_ID}.json").write_text(json.dumps(paused.to_dict()))
        before = self.files()
        result, output, errors = self.run_cli(["status"])
        self.assertEqual((result, errors), (0, ""))
        self.assertEqual(output.splitlines(), ["No active session.", "PAUSED: 1", "CREATED: 1"])
        self.assertEqual(self.files(), before)

    def test_status_displays_ended_pause_durations(self) -> None:
        self.save_created()
        active = Session(id=FIRST_ID, name="Calculus", goal="Solve problems", started_at=START,
                         pauses=[Pause(started_at=START + timedelta(minutes=30),
                                       ended_at=START + timedelta(minutes=40), reason="Break")])
        (self.root / "unfinished" / f"{FIRST_ID}.json").write_text(json.dumps(active.to_dict()))
        result, output, errors = self.run_cli(["status"], lambda: START + timedelta(hours=1))
        self.assertEqual((result, errors), (0, ""))
        for text in ("Active: 00:50:00", "Paused: 00:10:00", "Total elapsed: 01:00:00"):
            self.assertIn(text, output)

    @unittest.skipUnless(hasattr(time, "tzset"), "Requires local timezone selection")
    def test_status_uses_local_start_timezone_without_changing_utc_storage(self) -> None:
        self.save_created()
        self.store.start("1", clock=lambda: START)
        before = self.files()
        try:
            for tz, expected in (("EST5EDT,M3.2.0/2,M11.1.0/2", "2026-10-11 15:00:00-04:00"),
                                 ("UTC0", "2026-10-11 19:00:00+00:00")):
                with self.subTest(tz=tz):
                    with patch.dict(os.environ, {"TZ": tz}):
                        time.tzset()
                        result, output, errors = self.run_cli(["status"], lambda: START)
                    self.assertEqual((result, errors), (0, ""))
                    self.assertIn(f"Started: {expected}", output)
                    self.assertEqual(self.files(), before)
        finally:
            time.tzset()

    def test_invalid_selectors_and_transitions_have_clean_errors_without_changes(self) -> None:
        self.save_created()
        before = self.files()
        for selector in ("0", "bad", "2"):
            with self.subTest(selector=selector):
                result, output, errors = self.run_cli(["start", selector], lambda: START)
                self.assertEqual((result, output), (1, ""))
                self.assertIn("Run wsm sessions", errors)
                self.assertNotIn("Traceback", errors)
                self.assertEqual(self.files(), before)
        self.store.start("1", clock=lambda: START)
        before = self.files()
        result, output, errors = self.run_cli(["start", "1"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("already started", errors)
        self.assertEqual(self.files(), before)
        paused = self.store.resolve_selector("1")
        paused.pauses.append(Pause(started_at=START, ended_at=None, reason="Break"))
        (self.root / "unfinished" / f"{FIRST_ID}.json").write_text(json.dumps(paused.to_dict()))
        before = self.files()
        result, output, errors = self.run_cli(["start", "1"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("wsm resume", errors)
        self.assertEqual(self.files(), before)

    def test_clock_error_and_invalid_stored_timing_have_distinct_cli_messages(self) -> None:
        self.save_created()
        self.store.start("1", clock=lambda: START)
        before = self.files()
        result, output, errors = self.run_cli(["status"], lambda: START - timedelta(seconds=1))
        self.assertEqual((result, output), (1, ""))
        self.assertIn("system clock appears inconsistent", errors)
        self.assertNotIn("Invalid stored timing", errors)
        self.assertEqual(self.files(), before)
        path = self.root / "unfinished" / f"{FIRST_ID}.json"
        data = json.loads(path.read_text())
        data["started_at"] = "2026-10-11T19:00:00.000001+00:00"
        path.write_text(json.dumps(data))
        before = self.files()
        result, output, errors = self.run_cli(["status"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("Invalid stored timing", errors)
        self.assertIn(path.name, errors)
        self.assertNotIn("system clock appears inconsistent", errors)
        self.assertNotIn("Traceback", errors)
        self.assertEqual(self.files(), before)

    def test_failed_start_save_never_reports_success(self) -> None:
        self.save_created()
        before = self.files()
        with patch("os.replace", side_effect=OSError("Disk failure")):
            result, output, errors = self.run_cli(["start", "1"], lambda: START)
        self.assertEqual((result, output), (1, ""))
        self.assertIn("Disk failure", errors)
        self.assertEqual(self.files(), before)

    def test_start_requires_a_selector(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as raised:
                cli.main(["start"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("session", errors.getvalue())

    def test_multiple_active_sessions_stop_cli_operations_cleanly(self) -> None:
        self.save_created()
        for identity in (FIRST_ID, SECOND_ID):
            session = Session(id=identity, name="Active", goal="Work", started_at=START)
            (self.root / "unfinished" / f"{identity}.json").write_text(json.dumps(session.to_dict()))
        before = self.files()
        for arguments in (["status"], ["start", "1"]):
            with self.subTest(arguments=arguments):
                result, output, errors = self.run_cli(arguments, lambda: START)
                self.assertEqual((result, output), (1, ""))
                self.assertIn("multiple ACTIVE", errors)
                self.assertNotIn("Traceback", errors)
                self.assertEqual(self.files(), before)

    def test_create_list_start_and_status_persist_across_independent_processes(self) -> None:
        first, second = self.home / "first", self.home / "second"
        first.mkdir()
        second.mkdir()
        created = subprocess.run([sys.executable, "-m", "wsm", "create"], cwd=first,
                                 input="Calculus\nSolve problems\n", text=True,
                                 capture_output=True, timeout=10)
        self.assertEqual(created.returncode, 0, created.stderr)
        listed = subprocess.run([sys.executable, "-m", "wsm", "sessions"], cwd=second,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        mapping = (self.root / "selectors.json").read_bytes()
        # Independent commands supply time through the same main() boundary.
        for cwd, arguments, timestamp in (
            (first, ["start", "1"], "2026-10-11T19:00:00.999999+00:00"),
            (second, ["status"], "2026-10-11T20:00:00.999999+00:00"),
        ):
            code = ("from datetime import datetime; from wsm.cli import main; "
                    f"raise SystemExit(main({arguments!r}, "
                    f"clock=lambda: datetime.fromisoformat({timestamp!r})))")
            result = subprocess.run([sys.executable, "-c", code], cwd=cwd,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("State: ACTIVE", result.stdout)
        self.assertIn("Active: 01:00:00", result.stdout)
        self.assertIn("Total elapsed: 01:00:00", result.stdout)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        rejected = subprocess.run([sys.executable, "-m", "wsm", "start", "1"], cwd=second,
                                  text=True, capture_output=True, timeout=10)
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("already started", rejected.stderr)
        self.assertEqual(rejected.stdout, "")


if __name__ == "__main__":
    unittest.main()
