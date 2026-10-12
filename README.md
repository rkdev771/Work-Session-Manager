# Work Session Manager

WSM is a local, offline command-line tool for deliberate work: declare one
goal, start a session, explain pauses, and record whether you accomplished
the goal when you close it. Each command runs independently and exits.

## Installation

The project declares **Python 3.10 or newer** and has no runtime dependencies.
The current implementation requires a Unix platform with Python's `fcntl`
file locking (for example, Linux or macOS); native Windows is not supported.
The v0.1 verification environment used Python 3.14.7 on Linux. Other Python
versions and macOS have not been verified in this ticket.

From the repository directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
wsm --help
```

Installation uses setuptools as the build backend. Initial installation may
need access to packaging tools; installed WSM commands require no network.
The editable install means changes to `src/wsm/` are reflected without
reinstalling. Activate the virtual environment in each new terminal, or invoke
its executables by their full paths.

Both entry points provide the same commands:

```sh
wsm sessions
python -m wsm sessions
```

They work from any directory with the installed environment. Running `wsm`
without arguments displays help. Use `wsm --help` or a command's `--help`,
such as `wsm close --help`.

## A complete workflow

Start with an empty store for the example below. Type each line as a separate
shell command; WSM has no interactive command shell.

```sh
wsm create
# Title: Algebra
# Goal: Solve equations
wsm create
# Title: Biology
# Goal: Read chapter
wsm sessions
# 1  Algebra  CREATED
# 2  Biology  CREATED
wsm start 1
wsm status
wsm pause
# Pause reason: Lunch
wsm start 2
wsm pause
# Pause reason: Switch back
wsm close 2
# Close this session? [y/n]: yes
# Did you accomplish your goal? [y/n]: no
# Notes (optional): [press Enter for empty notes]
wsm resume 1
wsm close
# Close this session? [y/n]: yes
# Did you accomplish your goal? [y/n]: yes
# Notes (optional): Finished equations
wsm sessions
# No unfinished sessions.
wsm sessions --all
# No unfinished sessions.
# Algebra  CLOSED
# Biology  CLOSED
```

Use the numbers from your own latest listing if you already have sessions.
You can close the terminal between commands; timestamps and JSON preserve
the work and pauses. Duplicate titles are allowed and have distinct UUIDs.

| Command | Behavior |
| --- | --- |
| `wsm create` | Prompt for a title and one goal; save CREATED without starting. |
| `wsm sessions` | List unfinished sessions and rebuild their numeric selectors. |
| `wsm sessions --all` | Perform the same refresh, then append unnumbered CLOSED records. |
| `wsm start <session>` | Start a selected CREATED session if none is ACTIVE. |
| `wsm status` | Show an ACTIVE snapshot, or PAUSED and CREATED counts. |
| `wsm pause` | Pause the ACTIVE session with a required reason. |
| `wsm resume <session>` | Resume a selected PAUSED session if none is ACTIVE. |
| `wsm close [session]` | Close the ACTIVE session by default, or a selected ACTIVE/PAUSED session. |

Only one session may be ACTIVE. Starting or resuming another fails until you
pause or close the current one. Several sessions may remain PAUSED. An
explicitly selected PAUSED session can be closed while another is ACTIVE.
CREATED sessions cannot be closed; CLOSED sessions cannot be reopened.

Titles, goals, and pause reasons must contain nonwhitespace text; WSM trims
surrounding whitespace and retries blank input. Yes/no prompts accept `y`,
`yes`, `n`, and `no`, regardless of case. Partial goal completion means **no**;
optional notes can explain it. Empty notes are valid. Answering no to the
close confirmation, Ctrl-C, or end-of-input cancels without saving proposed
changes. Pause and close timestamps are captured before their prompts; input
retries retain that timestamp, so answering time does not add active work.

## Selectors

A listing sorts unfinished sessions by title, using UUID to break duplicate
title ties, and saves compact numbers from 1 onward. Both listing forms save
the same unfinished mapping. CLOSED records have no numbers.

Numbers refer to the **latest successful listing**, even across terminals.
Creating does not assign a number; list again to select a new session.
Starting, status, pausing, resuming, and closing do not refresh numbers.
Closing makes its old number unavailable without shifting the others. For
example, closing `2` leaves `1` and `3` pointing to the same sessions until
the next listing rebuilds them as `1` and `2`. Always read the latest listing
before choosing a number; a refreshed number can refer to a different session.

A missing or damaged mapping, invalid number, or number pointing to a missing
or CLOSED record produces an error directing you to `wsm sessions`. WSM never
guesses a replacement. A command already waiting for pause/close input keeps
its original UUID even if another terminal refreshes selectors.

## Local storage and timing

Data lives in your home directory, independently of the current directory:

```text
~/.wsm/
├── unfinished/<uuid>.json  # CREATED, ACTIVE, PAUSED
├── sessions/<uuid>.json    # CLOSED
├── selectors.json         # JSON object mapping number strings to UUID strings
└── .lock                  # Coordination between commands
```

Directories are created automatically. Schema version 1 records store the
title as `name`, the goal, UUIDv4 identity, and UTC events. State is derived
from those events. Unfinished records contain no duration counters. CLOSED
records include all pause ends, per-pause and final duration seconds, boolean
goal completion, and notes. The CLI preserves CLOSED archives unchanged.

WSM writes a temporary JSON file and atomically replaces its destination.
Close saves the complete archive before removing the unfinished copy. If
cleanup is interrupted, the next inventory operation verifies matching
copies and removes the leftover unfinished copy. Conflicting or malformed
data produces a file-specific error and is preserved. If an error says an
archive was saved but cleanup failed, the completed record exists; a later
command retries verified cleanup without new closing answers.

Brief file locks coordinate storage operations. Prompts hold no lock. If
another command changes a session while its pause/close answers are pending,
WSM rejects the stale save; run the command again against the current state.
Failures do not report the requested mutation as successful. Normal commands
return 0 on success, 1 on cancellation/errors, and 2 for invalid command usage;
declining the close confirmation returns 0 and reports cancellation.

There is no running stopwatch or background process. WSM captures the system
clock in UTC at whole-second precision and calculates:

- Total elapsed = endpoint minus session start.
- Paused = sum of pause intervals, including an open pause through the endpoint.
- Active = total elapsed minus paused.

Active time stays fixed while PAUSED. For start at 19:00, pause at 19:30,
resume at 19:40, and close at 20:00, total is 3600 seconds, paused is 600,
and active is 3000. Status displays the start in your current local timezone;
saved events stay UTC. Durations use `HH:MM:SS` and can exceed 24 hours.

UTC avoids timezone/daylight-saving ambiguity, but cannot recover true elapsed
time after arbitrary manual clock changes. Detectably backward timestamps
fail without saving the transition. Other clock changes can distort elapsed
time without detection; this is an accepted v0.1 limitation.

## Verification

After installing, run the standard-library suite:

```sh
python -m unittest discover -s tests
```

Tests use temporary stores and supplied times. Integration checks launch
independent CLI processes; pipe barriers coordinate overlap without sleeping
to simulate work. Time injection uses the existing Python
`wsm.cli.main(..., clock=...)` boundary, with no user-facing clock flag.
See [the v0.1 verification audit](docs/verification/v0.1.md) for coverage and
validation limits, and [the authoritative specification](docs/specifications/WSM_V0_1_SPEC.md)
for product requirements.

## v0.1 exclusions

WSM does not include GUI/TUI dashboards, widgets, live timers, task lists,
multiple goals, projects, categories, tags, automatic switching, or passive
activity detection. It has no Pomodoro/countdowns, reminders, scheduling,
calendar integration, or estimates.

There are no accounts, servers, APIs, cloud synchronization, AI features,
statistics, analytics, charts, streaks, achievements, pause analysis, or goal
completion reports. There are no separate history/detail commands, search,
filters beyond `sessions --all`, sorting options, pagination, or advanced
display controls. Editing, deleting, cancelling CREATED records, reopening
CLOSED records, importing, exporting, and Markdown reports are excluded.
