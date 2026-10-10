# Work Session Manager — v0.1 Specification

This is the single authoritative v0.1 product specification. It consolidates
the original MVP, the multi-session amendment, and the user-approved decisions
from the 2026-10-10 regrill and subsequent whole-second timing revision. The
user approved preservation verification and the specification authority switch.
Collaboration instructions are in the root `AGENTS.md`; individual tickets
are in `../tickets/v0.1/`.

## 1. Purpose and technical boundaries

Work Session Manager (WSM) is a local-first Python CLI for deliberate work
sessions. The accountability loop is: declare one goal, work, explain pauses,
report whether the goal was accomplished, and preserve the record.

- Every session has one required title and exactly one required goal.
- Every pause requires a reason.
- Goal completion is a boolean: yes or no. Partial completion is no; optional
  closing notes may explain the result.
- Normal operation is completely offline. There are no accounts, network
  services, synchronization, or external time authorities.
- Application data is local JSON. Sessions have UUIDv4 identities.
- Commands execute independently and exit. Closing the terminal between
  commands must not lose state or prevent later duration calculations.
- The computer's system clock supplies timezone-aware UTC timestamps.
  Timestamps, not continuously updated counters, are the timing authority.
- There is no background process or continuously running stopwatch.
- Prefer straightforward Python and the standard library. Runtime dependencies
  require a clear reason and the user's approval.

WSM is a session tool, not a general task manager or passive activity tracker.

## 2. Identity and lifecycle

The full UUIDv4 is a session's permanent internal identity and JSON filename.
It must not depend on its title, goal, date, time, selector, or sequence
position. Duplicate titles are allowed, including titles shared with CLOSED
sessions. Normal CLI use must not require typing UUIDs.

Every valid session has exactly one derived lifecycle state:

| State | Meaning |
| --- | --- |
| CREATED | Saved, but never started; `started_at` is null. |
| ACTIVE | Started, not closed, and no open latest pause. |
| PAUSED | Started, not closed, and the latest pause is open. |
| CLOSED | Has `ended_at`; all pauses are closed and closing data is present. |

There may be any number of CREATED, PAUSED, and CLOSED sessions, but at most
one ACTIVE session across the application store.

| Command | Required state | Result |
| --- | --- | --- |
| `create` | No existing session required | New CREATED session |
| `start <session>` | Selected session CREATED; no ACTIVE session | ACTIVE |
| `pause` | An ACTIVE session exists | That session becomes PAUSED |
| `resume <session>` | Selected session PAUSED; no ACTIVE session | ACTIVE |
| `close [session]` | Target ACTIVE or PAUSED | CLOSED after successful save |

Creating never starts work. Starting or resuming while any other session is
ACTIVE fails without automatically pausing or closing it. CLOSED is terminal:
no lifecycle command can reopen or modify a CLOSED session. CREATED sessions
cannot be closed, deleted, or cancelled in v0.1.

All other lifecycle transitions fail clearly without applying the requested
state change. Examples include starting an already started session, resuming
a CREATED or ACTIVE session, pausing without an ACTIVE session, and closing
a CREATED or CLOSED session.

## 3. Commands and help

These are separate shell commands, not commands inside an interactive WSM
prompt:

```text
wsm create
wsm sessions
wsm sessions --all
wsm status
wsm start <session>
wsm pause
wsm resume <session>
wsm close [session]
```

`<session>` is a numeric selector from the latest successful session listing.
`wsm --help` provides standard help for this command surface, and command help
explains its arguments and `--all`. Running `wsm` without a command displays
help. There is no `finish` command in amended v0.1.

### 3.1 Create

Prompt for title and goal, validate both, generate a UUIDv4, and immediately
persist a CREATED session. There is no start timestamp or accumulated work.
Creation is permitted while another session is ACTIVE.

Report creation and direct the user to run `wsm sessions` to obtain a selector.
Creation does not refresh or extend the existing selector mapping.

### 3.2 Sessions and selectors

Both `sessions` and `sessions --all` perform the same selector refresh:

1. Obtain a consistent inventory of valid unfinished sessions.
2. Sort unfinished sessions alphabetically by title, with UUID as a
   deterministic tie-breaker for identical titles.
3. Assign compact numeric selectors `1` through `N`.
4. Safely persist the number-to-UUID mapping and display that listing.

The unfinished listing includes selector, title, and state. A goal is not
required in this listing. With no unfinished sessions, report that clearly
and refresh to an empty mapping.

`--all` appends CLOSED records after the unfinished list. CLOSED entries show
title and state, have no numeric selectors, and do not consume numbers. The
unfinished selectors are identical for either listing command over the same
inventory. This is the sole v0.1 exception to the exclusion of filtering and
advanced display options.

The most recent successful listing is authoritative for numeric selection
across independent CLI executions:

- Resolve a number through the saved mapping to the permanent UUID.
- Creating, starting, pausing, resuming, status display, and closing do not
  reassign existing numbers.
- Closing makes its number unavailable. It must not redirect that number to
  another session or compact the remaining numbers automatically.
- The next listing rebuilds compact numbers; previously remembered numbers
  may then have different meanings. Users select from the latest listing.
- New sessions remain unnumbered until either listing command runs.
- Missing, malformed, nonpositive, or unknown selectors fail clearly. If no
  mapping exists, it is damaged, or a number points to a missing or CLOSED
  session, instruct the user to run `wsm sessions`.
- Numeric selectors are interaction conveniences, not persistent session
  identities. They are not stored as session identity fields.

For example, closing `2` leaves `1` and `3` pointing to their existing
sessions. `resume 2` fails. After another listing, the remaining unfinished
sessions become `1` and `2` in the displayed order.

### 3.3 Status

`status` is a snapshot of the currently ACTIVE session. Show its title,
goal, ACTIVE state, start date/time in the computer's current local timezone,
active duration, paused duration, and total elapsed duration.

Display durations as `HH:MM:SS`; hours may exceed 24 and must not wrap.
Stored timestamps remain UTC regardless of the display timezone.

When no session is ACTIVE, say `No active session.` and report the counts of
PAUSED and CREATED sessions. Status does not provide a selected PAUSED or
CLOSED session detail view, refresh selectors, or run a live timer.

### 3.4 Start and resume

Resolve and validate the selected session and verify that no session is
ACTIVE. Start records `started_at` and transitions CREATED to ACTIVE. Resume
sets the latest open pause's `ended_at` and transitions PAUSED to ACTIVE.
Capture the transition timestamp after validation and the ACTIVE check;
persist the change before reporting success.

Name and goal entry happen during create and therefore never count as work.
Starting PAUSED must direct the user to resume instead. Resuming CREATED must
explain that the session has not started.

### 3.5 Pause

Target the sole ACTIVE session without a selector. Capture a candidate pause
timestamp when the command begins, before prompting for a required reason.
After valid input, append an open pause with that timestamp and persist it.
Input retries retain the original candidate timestamp. Cancellation discards
it and does not commit a pause.

### 3.6 Close

With no selector, target the currently ACTIVE session; fail if none exists.
An explicit selector can target an ACTIVE or PAUSED session. Closing a PAUSED
session requires its selector and may occur while a different session is
ACTIVE; that other session is unaffected.

Capture a candidate end timestamp when the command begins, before prompts.
Identify the selected session, then ask:

```text
Close this session? [y/n]:
Did you accomplish your goal? [y/n]:
Notes (optional):
```

A no answer to the first question discards the candidate and leaves the
session unchanged. After yes, require goal completion and permit empty notes.
Input retries retain the candidate timestamp. Cancellation at any prompt
does not save a partially closed session.

On success, use the candidate for session `ended_at`. If PAUSED, also use it
for the latest open pause's `ended_at`. Calculate final durations, safely
archive the CLOSED record, and only then remove the unfinished copy. Report
completion, title, yes/no goal completion, and all three final durations.

## 4. Input and errors

Required title, goal, and pause reason must be strings containing nonwhitespace
text. Trim surrounding whitespace from these required inputs. Reject empty
or whitespace-only input and prompt again. Empty closing notes are valid.

Accept `y`, `yes`, `n`, and `no` case-insensitively; invalid answers prompt
again. Ctrl-C or end-of-input during any prompt cancels the command, reports
cancellation concisely, and saves none of its proposed changes.

Normal invalid input, invalid transitions, clock inconsistencies, conflicting
commands, and storage failures must produce clear errors rather than unhandled
exceptions. Errors must not report a mutation as successful. Invalid commands
must not apply their requested state change or overwrite saved session data.
Verified cleanup of an already completed close is the separate recovery
operation defined in section 7, not a new lifecycle transition.

## 5. Time and duration rules

Use whole-second precision for timing. Obtain timezone-aware UTC time from
the local system clock and discard its fractional seconds at the centralized
clock boundary, before using it as an event timestamp or calculation endpoint.
Persist generated timestamps as valid ISO 8601 UTC strings without fractional
seconds. Tests can supply predetermined timestamps through the same boundary.

For a started session, use the current command timestamp as the endpoint
unless CLOSED, in which case use its persisted `ended_at`:

```text
total_duration_seconds = seconds(endpoint - started_at)
pause_duration_seconds = seconds(pause_endpoint - pause.started_at)
paused_duration_seconds = sum(individual pause_duration_seconds)
active_duration_seconds = total_duration_seconds - paused_duration_seconds
```

`seconds` expresses a valid nonnegative timestamp difference as integer
seconds. All timing endpoints have whole-second precision, so durations need
no separate rounding rule or fractional-remainder allocation. An open pause
uses the same current endpoint as the total-duration calculation. An ended
pause uses its own `ended_at`. Final paused seconds equal the sum of recorded
pause seconds, and active plus paused equals total. Active duration stays fixed
while PAUSED. Subsecond precision is unnecessary for v0.1.

CREATED sessions have no work duration. Time before start is not counted.
An open pause continues accumulating paused time between commands without
a WSM process running. Closing PAUSED includes the open interval through the
candidate close timestamp.

For example, start at 19:00, pause at 19:30, resume at 19:40, and close at
20:00 gives total 3600, paused 600, and active 3000 seconds.

### 5.1 Timing validation and clock errors

Validate stored timestamps and their ordering before calculating durations.
Stored lifecycle timestamps used for v0.1 timing must have whole-second
precision. Reject:

- Pauses before session start or with ends before their starts.
- Out-of-order or overlapping pause intervals; only the final pause may be
  open, and a CLOSED session cannot have an open pause.
- A session end before its start or latest recorded event.
- Stored CLOSED duration fields inconsistent with the arithmetic above,
  including individual pause durations.
- A current command timestamp earlier than the required previous event for
  its calculation or transition.

Equal timestamps and zero-length intervals are valid. Never hide invalid
stored timing by clamping a negative duration to zero or rounding it away.
Distinguish invalid stored timing from a current-clock inconsistency. A clock
error must explain that the system clock appears inconsistent with the saved
timestamps and must not commit the proposed transition.

UTC prevents timezone and daylight-saving ambiguity, but cannot recover true
elapsed time after arbitrary manual system-clock changes. Clock changes that
do not produce a detectable inconsistency remain an accepted v0.1 limitation.

## 6. JSON representation

Session JSON uses schema version 1. Retain `name` as the persisted field for
the human-facing title; use UUID strings and ISO 8601 UTC timestamp strings.
State is derived, never duplicated as a stored state field.

Every session contains:

| Field | JSON value |
| --- | --- |
| `schema_version` | Integer `1` |
| `id` | UUIDv4 string |
| `name` | Required nonblank title string |
| `goal` | Required nonblank goal string |
| `started_at` | UTC timestamp string, or null while CREATED |
| `pauses` | Ordered array of pause objects; empty while CREATED |

Unfinished pauses contain `started_at`, `ended_at`, and `reason`. An open
pause has `ended_at: null`. Unfinished session JSON stores event data, not
duration counters or closing fields; derived pause durations are added to
the CLOSED representation.

A CLOSED record additionally requires:

| Field | JSON value |
| --- | --- |
| `ended_at` | UTC timestamp string |
| `active_duration_seconds` | Nonnegative integer |
| `paused_duration_seconds` | Nonnegative integer |
| `total_duration_seconds` | Nonnegative integer |
| `goal_completed` | Boolean |
| `notes` | String; may be empty |

Each CLOSED pause additionally requires nonnegative integer `duration_seconds`
and a nonnull end timestamp. Booleans are not integer duration values.
Final duration fields are derived records, not an alternative timing source.
Closed records are immutable through the v0.1 CLI.

Validate stored shape at serialization boundaries and validate timing when
loading or calculating session data for the implemented workflow. Unsupported
schema versions and malformed values fail cleanly. Do not interpret invalid
values as a different lifecycle state or silently fill missing required data.

## 7. Persistence and recovery

Use a stable application-data directory independent of the shell's current
directory. Create needed directories automatically:

```text
~/.wsm/
├── unfinished/
│   └── <full-uuid>.json       # CREATED, ACTIVE, or PAUSED
├── sessions/
│   └── <full-uuid>.json       # CLOSED
└── selectors.json            # Latest listing's number-to-UUID mapping
```

Selector mapping is separate from session records and is safely replaceable.
Its exact JSON encoding and the public storage interface are implementation
choices to explain within the relevant ticket. Missing or damaged mapping
must not trigger guesses at session numbers: a listing rebuilds it from
valid session inventory.

Write JSON to a temporary file, successfully close it, and atomically replace
the destination. A failed write must not leave a partial replacement or
destroy the previous valid record. Archived UUID identity must agree with
the filename, and conflicting saved identities must not be silently accepted.

Close constructs and validates the complete record before archiving. Archive
save failure preserves unfinished state. Successfully saving the archive
precedes removing unfinished state. Never overwrite an existing CLOSED record
with a new lifecycle result.

Malformed session files, unsupported schemas, inconsistent stored timing,
conflicting copies, and multiple ACTIVE sessions stop the operation with a
clear explanation identifying the affected data. Preserve the files; do not
silently skip bad records or repair session history.

### 7.1 Interrupted close

During the normal session inventory scan, storage checks whether a UUID exists
in both directories. Only such duplicates trigger deeper recovery comparison.
Recovery is centralized in storage, not repeated in command handlers or run
as an extra full verification pass for every command.

For a duplicate, verify that the archive is a valid CLOSED record representing
completion of that unfinished session: identity, title, goal, start timestamp,
and prior pause history must agree. If the unfinished copy was PAUSED, the
only added pause end must be the CLOSED session's end timestamp. Derived
durations and closing data must be valid. A matching archive is authoritative;
safely remove the leftover unfinished copy and never resurrect that session
or count it as ACTIVE. Its old selector is unavailable.

If the copies do not match, report an error and preserve both. Recovery must
also coordinate with other commands so it cannot remove a changed copy.
Failure to finish cleanup must not lose the completed archive or falsely
report successful cleanup.

### 7.2 Overlapping commands

Coordinate brief storage operations so simultaneous commands cannot create
multiple ACTIVE sessions, lose a persisted update, or corrupt selector mapping.
Resolve selections to UUIDs; a mapping refresh must not silently retarget an
operation already in progress. Recheck applicable invariants before saving.

Do not hold exclusive access while the user answers prompts. If another
command changes the selected session while pause or close input is pending,
reject the pending save clearly rather than overwriting newer state. Before
start or resume is saved, the no-other-ACTIVE check must remain valid under
concurrent execution. Locking and conflict detection mechanisms are ticket
design choices, not an additional process, server, or runtime dependency.

## 8. Exclusions

v0.1 excludes:

- GUI, TUI, full-screen dashboard, terminal widgets, mouse interaction,
  progress bars, and continuously updating live timers.
- Task lists, multiple goals per session, projects, categories, and tags.
- Multiple ACTIVE sessions, automatic session switching, and passive activity
  detection.
- Pomodoro, countdowns, reminders, scheduling, calendar integrations, and
  estimated work duration.
- Accounts, servers, APIs, cloud synchronization, and AI functionality.
- Statistics, analytics, charts, streaks, achievements, productivity patterns,
  pause analysis, and goal completion reports.
- Separate history or session-detail commands, search, filtering beyond
  `sessions --all`, sorting options, pagination, and advanced display controls.
- Editing or deleting saved sessions through the CLI, including cancellation
  or deletion of CREATED sessions and reopening CLOSED sessions.
- Importing, exporting, and Markdown reports.

Structured JSON can support later expansion; do not implement that expansion
or introduce speculative abstractions in v0.1.

## 9. Verification and completion

Use standard-library `unittest`. Tests supply timestamps without real waiting
and use temporary application-data directories rather than the user's data.
Verify observable behavior through public model methods, the agreed storage
interface, and CLI execution, including separate processes. Avoid assertions
coupled to private helper structure. Agree on each ticket's specific public
testing boundaries before adding tests.

Required coverage includes:

- Creation, required input, UUIDv4 generation/preservation, duplicate titles,
  schema handling, derived states, and serialization round trips.
- No pauses, one pause, multiple pauses, open pause, whole-second clock capture,
  fixed active duration while paused, zero-length intervals, duration arithmetic,
  invalid timestamp order, overlap detection, inconsistent derived fields,
  invalid stored timestamp precision, and backward clock errors.
- Start, pause, resume, close from ACTIVE and PAUSED, both goal results,
  empty notes, invalid transitions, and single-ACTIVE enforcement.
- Prompt retries, confirmation refusal, Ctrl-C/EOF, and pause/close candidate
  timestamps retained during retries and discarded on cancellation.
- Compact selector refresh from either listing, duplicate-title ordering,
  persisted mapping between processes, newly unnumbered sessions, unavailable
  numbers after close, damaged mapping, and CLOSED entries without numbers.
- ACTIVE status output, counts when none is ACTIVE, local timestamp display,
  and duration display without wrapping hours.
- Persistence between independent commands, atomic updates, malformed data,
  failed saves, archive-before-cleanup ordering, interrupted close recovery,
  conflicting duplicates, overlapping mutations, and changes during prompts.
- CLI help, invalid command usage, clear failures, and recovery without
  requiring a running WSM process.

v0.1 is complete when the persistent amended lifecycle works end to end:

1. Create several sessions with valid titles/goals and UUIDv4 identities.
2. List them and select one using its displayed number.
3. Start it, exit the CLI, and later obtain correct ACTIVE status from saved
   timestamps.
4. Pause with a required reason, exit again, and retain the open pause.
5. Start another CREATED session while the first remains PAUSED; attempts to
   start or resume another while one is ACTIVE fail without changing state.
6. Pause or close the ACTIVE session, then resume the chosen PAUSED session.
7. Close from either ACTIVE or PAUSED with confirmation, yes/no goal result,
   optional notes, correct final durations, and a complete UUID-named archive.
8. Remove unfinished state only after archival succeeds; a cancelled or failed
   close preserves unfinished state, and interrupted cleanup recovers safely.
9. Refresh selectors and verify CLOSED records are hidden by default and
   appended without numbers by `--all`.
10. Inspect JSON for correct identities, UTC timestamps, pauses, accountability,
    derived durations, and absence of duplicated state or unfinished counters.
11. Continue creating and running sessions across separate processes, with
    invalid input, timing errors, damaged data, and conflicting operations
    handled cleanly.

Working timing arithmetic alone is insufficient: the complete persistent
accountability loop and multi-session invariants must work reliably.

## 10. Existing implementation context

This section preserves implementation decisions and unfinished work; it does
not turn every current code choice into a product requirement.

The repository currently has a `src/` package layout so tests exercise the
installed package rather than accidental working-directory imports, an
installed `wsm` entry point, `python -m wsm` entry point, standard-library
`argparse` parser, help,
and separate empty handlers for all seven commands. `wsm.cli.main()` accepts
an optional argument sequence and returns an integer exit code, supporting
direct CLI tests. `sessions --all` is not implemented yet.

The small domain model keeps `SessionState`, `Pause`, and `Session` together in
`src/wsm/session.py`. Keyword-only dataclasses use typed `UUID` and `datetime`
values internally and strings at JSON boundaries. State is derived from
timestamps and the latest pause. Schema version 1, closing fields, and explicit
structural validation before serialization and after deserialization already
exist; validation is not automatic dataclass-construction validation.

The existing suite contains 27 tests: four CLI skeleton tests and 23 model,
state, serialization, and structural-validation tests. These completed pieces
must be preserved rather than ticketed for wholesale reimplementation.
Existing integer duration fields do not yet have calculation logic; structural
validation does not yet check chronology, overlap, or arithmetic consistency.
Some structural-test fixtures contain inconsistent derived durations and must
not be treated as approved timing behavior.

Remaining work includes storage and its public interface, system-clock access,
time arithmetic and validation, prompts, selector resolution, actual command
behavior, single-ACTIVE enforcement, archival/recovery, concurrency protection,
and the full workflow tests. Keep unfinished JSON event-only when integrating
pause duration calculation; review existing serialization behavior rather than
treating incidental acceptance of derived values as a new product requirement.

Storage tickets must explain the stable data directory, storage interface,
atomic writes, loading and malformed-file behavior, and meaningful alternatives
in beginner-friendly terms. Implement in small runnable user flows, preserving
completed work and keeping the distinction between structural and timing
validation clear. The project declares Python 3.10 or newer and uses no runtime
dependencies. New tooling requires demonstrated need and the required approval.

Collaboration rules are in the root `AGENTS.md`. Specification and ticket files
remain inside this repository without tracker statuses or labels. The seven
agreed tickets cover unfinished work; implement and review them one at a time.
The superseded specifications and project-status/workflow documents are retired
from active documentation, with their history retained in Git.
