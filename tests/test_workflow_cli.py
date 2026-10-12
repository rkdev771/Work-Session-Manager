"""Ticket 07: complete workflows through independent CLI processes."""

import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from wsm.session import Session, SessionState


START = datetime(2026, 10, 11, 19, tzinfo=timezone.utc)


class WorkflowCliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.root = self.home / ".wsm"
        self.environment = {**os.environ, "HOME": str(self.home), "TZ": "UTC0"}
        self.directories = [self.home / "first", self.home / "second"]
        for directory in self.directories:
            directory.mkdir()
        self.command_count = 0

    def process_options(self):
        directory = self.directories[self.command_count % 2]
        self.command_count += 1
        return dict(cwd=directory, env=self.environment, text=True)

    def timed_code(self, arguments, seconds):
        timestamp = (START + timedelta(seconds=seconds, microseconds=999999)).isoformat()
        return ("from datetime import datetime; from wsm.cli import main; "
                f"raise SystemExit(main({arguments!r}, "
                f"clock=lambda: datetime.fromisoformat({timestamp!r})))")

    def run_cli(self, arguments, seconds=None, answers="", expected=0):
        command = ([sys.executable, "-m", "wsm", *arguments] if seconds is None
                   else [sys.executable, "-c", self.timed_code(arguments, seconds)])
        result = subprocess.run(command, input=answers, capture_output=True,
                                timeout=10, **self.process_options())
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        if expected == 0:
            self.assertEqual(result.stderr, "")
        return result

    def mapping(self):
        return json.loads((self.root / "selectors.json").read_text())

    def records(self, directory="unfinished"):
        return {path.stem: json.loads(path.read_text())
                for path in (self.root / directory).glob("*.json")}

    def files(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*.json")}

    def begin_waiting_cli(self, arguments, seconds, *, at_prompt=False):
        """Wait for a child to reach a pipe barrier or its first input prompt."""
        reader, writer = os.pipe()
        prelude = f"import os, sys\nos.write({writer}, b'R')\nos.close({writer})\n"
        if at_prompt:
            prelude = (
                "import os\nfrom unittest.mock import patch\n"
                "original_input = input\nready = False\n"
                "def answer(prompt):\n"
                "    global ready\n"
                "    if not ready:\n"
                f"        os.write({writer}, b'R')\n"
                f"        os.close({writer})\n"
                "        ready = True\n"
                "    return original_input(prompt)\n"
                "patch('builtins.input', side_effect=answer).start()\n"
            )
        else:
            prelude += "sys.stdin.readline()\n"
        try:
            process = subprocess.Popen(
                [sys.executable, "-c", prelude + self.timed_code(arguments, seconds)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                pass_fds=(writer,), **self.process_options())
            self.addCleanup(self.cleanup_process, process)
        finally:
            os.close(writer)
        try:
            self.assertTrue(select.select([reader], [], [], 10)[0], "CLI did not reach its barrier")
            self.assertEqual(os.read(reader, 1), b"R", "CLI exited before its barrier")
        finally:
            os.close(reader)
        return process

    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def test_competing_cli_transitions_allow_only_one_active_session(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                # Each race gets independent application data.
                self.environment["HOME"] = str(self.home / str(resume))
                self.root = Path(self.environment["HOME"]) / ".wsm"
                self.run_cli(["create"], answers="Algebra\nSolve\n")
                self.run_cli(["create"], answers="Biology\nRead\n")
                self.run_cli(["sessions"])
                if resume:
                    self.run_cli(["start", "1"], 0)
                    self.run_cli(["pause"], 10, "Break\n")
                before = self.files()
                first_command = ["resume" if resume else "start", "1"]
                processes = [self.begin_waiting_cli(first_command, 20),
                             self.begin_waiting_cli(["start", "2"], 20)]
                for process in processes:
                    process.stdin.write("\n")
                    process.stdin.flush()
                outcomes = [process.communicate(timeout=10) for process in processes]
                self.assertEqual(sorted(process.returncode for process in processes), [0, 1])
                loser = next(index for index, process in enumerate(processes) if process.returncode == 1)
                self.assertEqual(outcomes[loser][0], "")
                self.assertIn("ACTIVE session already exists", outcomes[loser][1])
                winner = 1 - loser
                self.assertEqual(outcomes[winner][1], "")
                loser_id = self.mapping()[str(loser + 1)]
                loser_file = f"unfinished/{loser_id}.json"
                self.assertEqual(self.files()[loser_file], before[loser_file])
                self.assertEqual(self.files()["selectors.json"], before["selectors.json"])
                states = [Session.from_dict(data).state for data in self.records().values()]
                self.assertEqual(states.count(SessionState.ACTIVE), 1)
                for identity in self.records():
                    self.assert_unfinished(identity, Session.from_dict(self.records()[identity]).state)
                status = self.run_cli(["status"], 30)
                expected_title = "Algebra" if winner == 0 else "Biology"
                self.assertIn(f"Title: {expected_title}", status.stdout)

    def test_pending_cli_prompts_survive_refresh_and_reject_changed_records(self):
        for command, paused in (("pause", False), ("close", False), ("close", True)):
            for change in (False, True):
                with self.subTest(command=command, paused=paused, change=change):
                    self.environment["HOME"] = str(self.home / f"{command}-{paused}-{change}")
                    self.root = Path(self.environment["HOME"]) / ".wsm"
                    self.run_cli(["create"], answers="Work\nFinish\n")
                    self.run_cli(["sessions"])
                    identity = self.mapping()["1"]
                    self.run_cli(["start", "1"], 0)
                    if paused:
                        self.run_cli(["pause"], 10, "Original break\n")
                    arguments = ["close", "1"] if command == "close" else ["pause"]
                    pending = self.begin_waiting_cli(arguments, 20, at_prompt=True)
                    # This also proves prompts release the store lock.
                    self.run_cli(["create"], answers="Algebra\nRead\n")
                    listed = self.run_cli(["sessions", "--all"])
                    self.assertIn("1  Algebra  CREATED", listed.stdout)
                    self.assertEqual(self.mapping()["2"], identity)
                    if change:
                        if paused:
                            self.run_cli(["resume", "2"], 30)
                        else:
                            self.run_cli(["pause"], 30, "New break\n")
                    before = self.files()
                    answers = "Candidate break\n" if command == "pause" else "y\ny\n\n"
                    output, errors = pending.communicate(input=answers, timeout=10)
                    if change:
                        self.assertEqual(pending.returncode, 1, output + errors)
                        self.assertIn(f"changed while {command} input was pending", errors)
                        self.assertNotIn("Traceback", errors)
                        self.assertEqual(self.files(), before)
                        self.assertNotIn("Paused session:" if command == "pause" else "Closed session:", output)
                    else:
                        self.assertEqual(pending.returncode, 0, output + errors)
                        self.assertEqual(errors, "")
                        self.assertEqual((self.root / "selectors.json").read_bytes(), before["selectors.json"])
                        if command == "pause":
                            session = self.assert_unfinished(identity, SessionState.PAUSED)
                            self.assertEqual(session.pauses[-1].started_at, START + timedelta(seconds=20))
                        else:
                            self.assertNotIn(identity, self.records())
                            closed = Session.from_dict(self.records("sessions")[identity])
                            closed.validate_timing()
                            self.assertEqual(closed.state, SessionState.CLOSED)
                            self.assertEqual(closed.ended_at, START + timedelta(seconds=20))

    def test_installed_entry_points_offer_complete_help_without_mutating_data(self):
        console = Path(sys.executable).with_name("wsm")
        self.assertTrue(console.is_file(), "Install the package editably before running tests")
        for entry_point in ([str(console)], [sys.executable, "-m", "wsm"]):
            for arguments in ([], ["--help"], *([command, "--help"] for command in
                              ("create", "sessions", "start", "status", "pause", "resume", "close"))):
                with self.subTest(entry_point=entry_point, arguments=arguments):
                    result = subprocess.run([*entry_point, *arguments], capture_output=True,
                                            timeout=10, **self.process_options())
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertIn("usage: wsm", result.stdout)
                    if arguments in ([], ["--help"]):
                        for command in ("create", "sessions", "start", "status", "pause", "resume", "close"):
                            self.assertIn(command, result.stdout)
                        self.assertNotIn("finish", result.stdout)
                    if arguments == ["sessions", "--help"]:
                        self.assertIn("--all", result.stdout)
                    if arguments in (["start", "--help"], ["resume", "--help"], ["close", "--help"]):
                        self.assertIn("session", result.stdout)
            for arguments in (["finish"], ["start"], ["resume"]):
                result = subprocess.run([*entry_point, *arguments], capture_output=True,
                                        timeout=10, **self.process_options())
                self.assertEqual(result.returncode, 2)
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.root.exists())

    def assert_unfinished(self, identity, state):
        data = self.records()[identity]
        self.assertEqual(set(data), {"schema_version", "id", "name", "goal",
                                     "started_at", "pauses"})
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(UUID(identity).version, 4)
        self.assertEqual(data["id"], identity)
        session = Session.from_dict(data)
        session.validate_timing()
        self.assertEqual(session.state, state)
        for pause in data["pauses"]:
            self.assertEqual(set(pause), {"started_at", "ended_at", "reason"})
        return session

    def test_complete_accountability_loop_persists_across_processes(self):
        self.assertEqual(self.run_cli(["status"]).stdout.splitlines(),
                         ["No active session.", "PAUSED: 0", "CREATED: 0"])
        self.run_cli(["create"], answers="Algebra\nSolve equations\n")
        self.run_cli(["create"], answers="Biology\nRead chapter\n")
        self.assertFalse((self.root / "selectors.json").exists())
        listed = self.run_cli(["sessions"])
        self.assertEqual(listed.stdout.splitlines(),
                         ["1  Algebra  CREATED", "2  Biology  CREATED"])
        first, second = self.mapping()["1"], self.mapping()["2"]
        self.assertNotEqual(first, second)
        self.assert_unfinished(first, SessionState.CREATED)
        self.assert_unfinished(second, SessionState.CREATED)
        mapping = (self.root / "selectors.json").read_bytes()

        self.run_cli(["start", "1"], 0)
        status = self.run_cli(["status"], 1800)
        for text in ("Title: Algebra", "Goal: Solve equations", "State: ACTIVE",
                     "Started: 2026-10-11 19:00:00+00:00", "Active: 00:30:00"):
            self.assertIn(text, status.stdout)
        self.run_cli(["pause"], 1800, " Lunch \n")
        paused = self.assert_unfinished(first, SessionState.PAUSED)
        self.assertEqual(paused.pauses[0].reason, "Lunch")
        self.assertEqual(paused.durations(START + timedelta(seconds=2400)).active_seconds, 1800)
        self.assertEqual(paused.durations(START + timedelta(seconds=3000)).active_seconds, 1800)
        self.run_cli(["start", "2"], 1800)
        before = self.files()
        rejected = self.run_cli(["resume", "1"], 1900, expected=1)
        self.assertIn("ACTIVE session already exists", rejected.stderr)
        self.assertEqual(self.files(), before)
        self.run_cli(["pause"], 2100, "Switch back\n")
        self.assert_unfinished(second, SessionState.PAUSED)
        closed = self.run_cli(["close", "2"], 2400, "yes\nno\n\n")
        for text in ("Goal completed: no", "Active: 00:05:00", "Paused: 00:05:00",
                     "Total elapsed: 00:10:00"):
            self.assertIn(text, closed.stdout)
        self.assertEqual((self.root / "selectors.json").read_bytes(), mapping)
        before = self.files()
        rejected = self.run_cli(["resume", "2"], 2400, expected=1)
        self.assertIn("missing or CLOSED", rejected.stderr)
        self.assertEqual(self.files(), before)
        self.run_cli(["resume", "1"], 2400)
        self.assert_unfinished(first, SessionState.ACTIVE)
        closed = self.run_cli(["close"], 3600, "y\ny\nFinished equations\n")
        for text in ("Goal completed: yes", "Active: 00:50:00", "Paused: 00:10:00",
                     "Total elapsed: 01:00:00"):
            self.assertIn(text, closed.stdout)
        self.assertEqual(self.records(), {})

        archives = self.records("sessions")
        self.assertEqual(set(archives), {first, second})
        for identity, active, paused_seconds, total, goal, notes in (
            (first, 3000, 600, 3600, True, "Finished equations"),
            (second, 300, 300, 600, False, ""),
        ):
            data = archives[identity]
            self.assertEqual((data["schema_version"], data["id"]), (1, identity))
            self.assertEqual(UUID(identity).version, 4)
            self.assertNotIn("state", data)
            self.assertNotIn("selector", data)
            self.assertEqual((data["active_duration_seconds"], data["paused_duration_seconds"],
                              data["total_duration_seconds"]), (active, paused_seconds, total))
            self.assertIs(data["goal_completed"], goal)
            self.assertEqual(data["notes"], notes)
            self.assertEqual(data["pauses"][0]["duration_seconds"], paused_seconds)
            session = Session.from_dict(data)
            session.validate_timing()
            self.assertEqual(session.state, SessionState.CLOSED)
            timestamps = [data["started_at"], data["ended_at"]]
            for pause in data["pauses"]:
                timestamps.extend([pause["started_at"], pause["ended_at"]])
            for timestamp in timestamps:
                self.assertTrue(timestamp.endswith("+00:00"))
                self.assertNotIn(".", timestamp)
        archive_bytes = {path.name: path.read_bytes() for path in (self.root / "sessions").glob("*.json")}
        self.assertEqual(self.run_cli(["sessions"]).stdout.strip(), "No unfinished sessions.")
        self.assertEqual(self.mapping(), {})

        # Duplicate titles and new sessions acquire numbers only on a listing.
        self.run_cli(["create"], answers="Algebra\nAnother goal\n")
        self.run_cli(["create"], answers="Algebra\nThird goal\n")
        self.assertEqual(self.mapping(), {})
        before = self.files()
        self.run_cli(["start", "1"], 4000, expected=1)
        self.assertEqual(self.files(), before)
        identities = sorted(self.records())
        all_listing = self.run_cli(["sessions", "--all"])
        self.assertEqual(all_listing.stdout.splitlines(),
                         ["1  Algebra  CREATED", "2  Algebra  CREATED",
                          "Algebra  CLOSED", "Biology  CLOSED"])
        self.assertEqual(self.mapping(), {"1": identities[0], "2": identities[1]})
        compact_mapping = (self.root / "selectors.json").read_bytes()
        self.run_cli(["sessions"])
        self.assertEqual((self.root / "selectors.json").read_bytes(), compact_mapping)
        self.assertEqual({path.name: path.read_bytes() for path in (self.root / "sessions").glob("*.json")},
                         archive_bytes)
        for directory in self.directories:
            self.assertFalse((directory / ".wsm").exists())
