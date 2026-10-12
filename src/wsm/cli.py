"""Command-line interface for Work Session Manager."""

import argparse
import sys
from collections.abc import Sequence
from uuid import uuid4

from wsm.clock import Clock, ClockError
from wsm.session import Session
from wsm.storage import SessionStore, StorageError


def _prompt_required(label: str) -> str:
    """Retry blank input, leaving cancellation to the command boundary."""
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print(f"{label} must contain nonwhitespace text.")


def handle_create(_args: argparse.Namespace) -> int:
    """Prompt for and persist a session without starting it."""
    name = _prompt_required("Title")
    goal = _prompt_required("Goal")
    session = Session(id=uuid4(), name=name, goal=goal)
    SessionStore().save_created(session)
    print(f"Created session: {session.name}. Run wsm sessions to obtain a selector.")
    return 0


def handle_sessions(_args: argparse.Namespace) -> int:
    """Refresh selectors and display saved unfinished sessions."""
    listing = SessionStore().refresh_selectors()
    if not listing:
        print("No unfinished sessions.")
    for number, session in listing:
        print(f"{number}  {session.name}  {session.state.value}")
    return 0


def _format_duration(seconds: int) -> str:
    """Format elapsed seconds without wrapping hours at a day boundary."""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def handle_status(args: argparse.Namespace) -> int:
    """Display a single saved ACTIVE snapshot or unfinished state counts."""
    snapshot = SessionStore().status(clock=args.clock)
    if snapshot.active is None:
        print("No active session.")
        print(f"PAUSED: {snapshot.paused_count}")
        print(f"CREATED: {snapshot.created_count}")
        return 0
    session = snapshot.active
    durations = snapshot.durations
    print(f"Title: {session.name}")
    print(f"Goal: {session.goal}")
    print(f"State: {session.state.value}")
    print(f"Started: {session.started_at.astimezone().isoformat(sep=' ', timespec='seconds')}")
    print(f"Active: {_format_duration(durations.active_seconds)}")
    print(f"Paused: {_format_duration(durations.paused_seconds)}")
    print(f"Total elapsed: {_format_duration(durations.total_seconds)}")
    return 0


def handle_start(args: argparse.Namespace) -> int:
    """Start a CREATED selection and report only after persistence succeeds."""
    session = SessionStore().start(args.session, clock=args.clock)
    print(f"Started session: {session.name}.")
    return 0


def handle_pause(args: argparse.Namespace) -> int:
    """Capture before input and persist only an unchanged ACTIVE target."""
    store = SessionStore()
    pending = store.capture_pause(clock=args.clock)
    reason = _prompt_required("Pause reason")
    session = store.commit_pause(pending, reason)
    print(f"Paused session: {session.name}.")
    return 0


def handle_resume(args: argparse.Namespace) -> int:
    """Resume a PAUSED selection and report after successful persistence."""
    session = SessionStore().resume(args.session, clock=args.clock)
    print(f"Resumed session: {session.name}.")
    return 0


def _prompt_yes_no(label: str) -> bool:
    """Retry invalid answers without recapturing the candidate timestamp."""
    while True:
        value = input(f"{label} [y/n]: ").strip().lower()
        if value in ("y", "yes", "n", "no"):
            return value in ("y", "yes")
        print("Please answer y/yes or n/no.")


def handle_close(args: argparse.Namespace) -> int:
    """Collect accountability answers without holding storage access."""
    store = SessionStore()
    pending = store.capture_close(args.session, clock=args.clock)
    if not _prompt_yes_no("Close this session?"):
        print("Close cancelled.")
        return 0
    goal_completed = _prompt_yes_no("Did you accomplish your goal?")
    notes = input("Notes (optional): ")
    session = store.commit_close(pending, goal_completed, notes)
    durations = session.durations()
    print(f"Closed session: {session.name}.")
    print(f"Goal completed: {'yes' if session.goal_completed else 'no'}")
    print(f"Active: {_format_duration(durations.active_seconds)}")
    print(f"Paused: {_format_duration(durations.paused_seconds)}")
    print(f"Total elapsed: {_format_duration(durations.total_seconds)}")
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

    resume_parser = subparsers.add_parser("resume", help="Resume a selected paused session.")
    resume_parser.add_argument("session", help="Session selector.")
    resume_parser.set_defaults(handler=handle_resume)

    close_parser = subparsers.add_parser("close", help="Close a work session.")
    close_parser.add_argument("session", nargs="?", help="Optional session selector.")
    close_parser.set_defaults(handler=handle_close)

    return parser


def main(argv: Sequence[str] | None = None, *, clock: Clock | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    args.clock = clock

    if not hasattr(args, "handler"):
        parser.print_help()
        return 0

    try:
        return args.handler(args)
    except (KeyboardInterrupt, EOFError):
        print("\nCommand cancelled.", file=sys.stderr)
        return 1
    except (StorageError, ClockError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
