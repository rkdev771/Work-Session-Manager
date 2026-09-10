"""Command-line interface for Work Session Manager."""

import argparse
from collections.abc import Sequence


def handle_create(_args: argparse.Namespace) -> int:
    """Handle the create command."""
    return 0


def handle_sessions(_args: argparse.Namespace) -> int:
    """Handle the sessions command."""
    return 0


def handle_status(_args: argparse.Namespace) -> int:
    """Handle the status command."""
    return 0


def handle_start(_args: argparse.Namespace) -> int:
    """Handle the start command."""
    return 0


def handle_pause(_args: argparse.Namespace) -> int:
    """Handle the pause command."""
    return 0


def handle_resume(_args: argparse.Namespace) -> int:
    """Handle the resume command."""
    return 0


def handle_close(_args: argparse.Namespace) -> int:
    """Handle the close command."""
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create and configure the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="wsm",
        description="Manage intentional work sessions.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    create_parser = subparsers.add_parser("create", help="Create a work session.")
    create_parser.set_defaults(handler=handle_create)

    sessions_parser = subparsers.add_parser("sessions", help="List saved sessions.")
    sessions_parser.set_defaults(handler=handle_sessions)

    status_parser = subparsers.add_parser("status", help="Show the current session.")
    status_parser.set_defaults(handler=handle_status)

    start_parser = subparsers.add_parser("start", help="Start a work session.")
    start_parser.add_argument("session", help="Session selector.")
    start_parser.set_defaults(handler=handle_start)

    pause_parser = subparsers.add_parser("pause", help="Pause the current session.")
    pause_parser.set_defaults(handler=handle_pause)

    resume_parser = subparsers.add_parser("resume", help="Resume the current session.")
    resume_parser.add_argument("session", help="Session selector.")
    resume_parser.set_defaults(handler=handle_resume)

    close_parser = subparsers.add_parser("close", help="Close a work session.")
    close_parser.add_argument("session", nargs="?", help="Optional session selector.")
    close_parser.set_defaults(handler=handle_close)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 0

    return args.handler(args)
