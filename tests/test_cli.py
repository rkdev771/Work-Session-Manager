"""Tests for the Phase 1 command-line skeleton."""

import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from wsm import cli


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


if __name__ == "__main__":
    unittest.main()
