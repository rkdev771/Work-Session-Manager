# Work Session Manager — Official MVP Specification

## 1. Product Overview

Work Session Manager (WSM) is a **local-first Python CLI application** for intentional work sessions.

The basic workflow is:

1. The user starts a session.
2. The user gives the session a name.
3. The user defines one concrete goal.
4. The session begins.
5. The user may pause the session at any time.
6. Every pause requires a reason.
7. The user resumes when they return to work.
8. The user finishes the session.
9. The user reports whether the original goal was completed.
10. The user may provide optional closing notes.
11. The completed session is permanently saved as local JSON data.

WSM is not intended to be a general task manager or passive time tracker.

Its purpose is to make work more intentional and accountable.

---

# 2. MVP Technical Constraints

The MVP must:

- be written in **Python**
- function completely offline
- require no network connection during normal operation
- use the computer's **system clock** as its only source of date and time
- store application data locally as JSON
- use **UUIDv4** identifiers for sessions
- operate as a command-line application
- work through independent CLI command executions
- not require a continuously running background process
- not implement an actual continuously incrementing stopwatch

For the MVP, Python's standard library should be sufficient.

Likely standard-library modules include:

```python
argparse
datetime
json
pathlib
uuid
```

Additional runtime dependencies should not be added unless there is a clear reason.

---

# 3. Core Product Principles

## 3.1 Session-first

The primary concept is a **work session**.

The application is not a to-do list.

A session represents a deliberate period of work directed toward one declared goal.

---

## 3.2 One goal per session

Every session must have exactly one goal.

Example:

```text
Session: Calculus Homework
Goal: Complete problems 1-20
```

The goal defines the condition for success.

---

## 3.3 Binary accountability

When a session ends, the user must answer:

```text
Did you accomplish your goal? [y/n]
```

The result is strictly:

```text
Yes
No
```

There is no `Partial` result.

If the user partially completed the goal, the correct result is `No`.

Additional context may be recorded in the notes.

---

## 3.4 Intentional pauses

Every pause must have a reason.

Example:

```text
Why are you pausing? Lunch
```

An empty pause reason is not valid.

The purpose is to add a small amount of intentional friction to interruptions without making the application cumbersome.

---

## 3.5 Local-first

All information belongs to the local application.

The MVP requires:

- no user accounts
- no cloud database
- no synchronization
- no server
- no API
- no internet access

---

## 3.6 Timestamps, not a running timer

WSM must **not maintain a continuously running stopwatch**.

Instead, the application records timestamps when meaningful events occur.

For example:

```text
session started
pause started
pause ended
session ended
```

When the user requests the current session status, WSM reads the saved timestamps, asks the system clock for the current time, and calculates the durations.

Therefore:

```text
wsm start
```

may terminate immediately after saving the session.

The terminal may then be closed completely.

Hours later:

```text
wsm status
```

must still calculate the correct session duration from persisted timestamps.

No WSM process needs to remain running.

---

# 4. MVP Scope

The MVP includes:

- creating a work session
- assigning a unique session ID
- defining a session name
- defining one goal
- recording the start timestamp
- viewing current session status
- pausing
- mandatory pause reasons
- resuming
- finishing a session
- reporting goal completion as yes/no
- optional closing notes
- calculating active work duration
- calculating paused duration
- calculating total elapsed duration
- persisting unfinished session state
- permanently storing completed sessions
- surviving normal terminal/program closure between commands
- handling normal invalid user input cleanly

The MVP does **not** include:

- GUI
- TUI dashboard
- task lists
- multiple goals
- projects
- categories
- tags
- multiple simultaneous sessions
- Pomodoro functionality
- countdown timers
- reminders
- scheduling
- calendar integrations
- cloud synchronization
- user accounts
- AI
- automatic activity detection
- statistics
- analytics
- charts
- streaks
- achievements
- estimated work duration
- session history commands
- editing old sessions
- deleting old sessions through the CLI
- Markdown reports
- data importing
- data exporting

Those may be considered after the MVP works reliably.

---

# 5. Session Identifier

Every session receives a **UUIDv4** when it is created.

Python can generate the ID locally:

```python
uuid.uuid4()
```

Example:

```text
550e8400-e29b-41d4-a716-446655440000
```

UUID generation requires no internet connection.

The full UUID is the session's canonical identifier.

The ID must never depend on:

- session name
- goal
- date
- time
- position in a sequence

This allows multiple sessions to have identical names without creating ambiguity.

Example:

```text
Calculus Homework
Calculus Homework
Calculus Homework
```

Each still has an independent identity.

The UUID also allows future functionality such as:

```text
wsm show <id>
wsm edit <id>
wsm delete <id>
```

Future versions may allow users to enter an unambiguous shortened UUID prefix, similar to abbreviated Git commit hashes.

Shortened IDs are **not required for the MVP**.

---

# 6. Timestamp Standard

All persisted timestamps must be:

- timezone-aware
- valid ISO 8601
- stored in UTC

Example:

```text
2026-09-08T19:42:00+00:00
```

The application should obtain time from the local computer's system clock.

Conceptually:

```python
datetime.now(timezone.utc)
```

No external time service may be used.

---

## 6.1 Why store UTC?

UTC avoids ambiguity caused by:

- daylight-saving-time transitions
- local timezone changes
- traveling between time zones

Human-facing CLI output may convert stored timestamps into the computer's current local timezone for display.

The stored JSON remains UTC.

---

# 7. Time Calculation Model

Timestamps are the authoritative timing data.

The program does not increment a counter every second.

For any timestamp:

```text
current_time = system clock at command execution
```

Total elapsed time is conceptually:

```text
current_time - started_at
```

or, for a completed session:

```text
ended_at - started_at
```

Paused time is calculated from recorded pause intervals.

Active time is:

```text
active_duration =
total_elapsed_duration
-
total_paused_duration
```

Durations should ultimately be represented in seconds.

---

# 8. Timing Behavior While Active

Example:

```text
started_at = 14:00
current_time = 15:30
```

No pauses occurred.

Therefore:

```text
total elapsed = 1h 30m
paused = 0m
active = 1h 30m
```

The application did not need to run during those 90 minutes.

---

# 9. Timing Behavior While Paused

Suppose:

```text
session started     14:00
pause started       14:45
current time        15:15
```

Then:

```text
total elapsed = 1h 15m
paused = 30m
active = 45m
```

An unfinished pause therefore contributes to paused time up to the system's current timestamp.

---

# 10. Session States

Conceptually, WSM has four states:

```text
IDLE
ACTIVE
PAUSED
FINISHED
```

`FINISHED` sessions are archived and are no longer the current session.

The valid state transitions are:

```text
IDLE
 |
 | start
 v
ACTIVE
 |
 | pause
 v
PAUSED
 |
 | resume
 v
ACTIVE
```

A session may finish from either:

```text
ACTIVE -> FINISHED
```

or:

```text
PAUSED -> FINISHED
```

Only one unfinished session may exist at a time.

---

# 11. Session Creation

Command:

```bash
wsm start
```

The CLI asks:

```text
Session name:
Goal:
```

Both fields are required.

Example:

```text
Session name: Calculus Homework
Goal: Complete problems 1-20

Session started.
```

The session's UUID is generated automatically.

The session start timestamp should be captured **after the required session information has been entered**, so time spent typing the name and goal does not count as work time.

The session is then persisted immediately.

---

# 12. Status Command

Command:

```bash
wsm status
```

The command reads the current session data and obtains the current system timestamp.

It then calculates the current durations.

Example while active:

```text
Session: Calculus Homework
Goal: Complete problems 1-20
Status: ACTIVE

Active time: 00:43:18
Paused time: 00:00:00
Total elapsed: 00:43:18
```

Example while paused:

```text
Session: Calculus Homework
Goal: Complete problems 1-20
Status: PAUSED

Active time: 00:43:18
Paused time: 00:08:12
Total elapsed: 00:51:30
```

When no unfinished session exists:

```text
No active session.
```

`status` displays a snapshot.

It does not launch a live updating stopwatch.

---

# 13. Pause Command

Command:

```bash
wsm pause
```

Valid only when a session is active.

The application asks:

```text
Why are you pausing?
```

The reason is required.

Example:

```text
Why are you pausing? Lunch

Session paused.
```

A pause contains:

```text
started_at
ended_at
reason
```

While the pause is ongoing:

```text
ended_at = null
```

The pause start time should represent when the pause command was initiated, rather than time after the user finishes typing the explanation.

If pause creation is cancelled or fails validation, no pause should be committed.

Attempting to pause an already paused session must fail cleanly.

---

# 14. Resume Command

Command:

```bash
wsm resume
```

Valid only while the current session is paused.

The resume command:

1. obtains the current system timestamp
2. assigns it to the open pause's `ended_at`
3. persists the updated session

Example:

```text
Session resumed.
```

Attempting to resume an already active session must fail cleanly.

---

# 15. Finish Command

Command:

```bash
wsm finish
```

When the command begins, WSM should capture a candidate finish timestamp from the system clock.

This prevents time spent answering closing questions from artificially increasing work duration.

The application asks:

```text
Finish this session? [y/n]:
```

If the user answers `No`, the candidate finish timestamp is discarded and the session remains unchanged.

If the user answers `Yes`, ask:

```text
Did you accomplish your goal? [y/n]:
Notes (optional):
```

The goal-completion answer is required.

Notes may be empty.

The captured finish timestamp becomes:

```text
ended_at
```

If the session was paused when `finish` was invoked, the currently open pause receives the same timestamp as its `ended_at`.

WSM then calculates final durations and saves the completed session.

Example:

```text
Session complete.

Session: Calculus Homework
Goal completed: No

Active time: 01:14:32
Paused time: 00:12:07
Total elapsed: 01:26:39
```

---

# 16. Goal Completion Data

Completed sessions contain:

```text
goal_completed
notes
```

`goal_completed` is a boolean.

Valid stored values:

```json
true
```

or:

```json
false
```

Example:

```text
Goal: Complete problems 1-20
Completed: No
Notes: Completed problems 1-16. Problems 17-20 took longer than expected.
```

There is intentionally no partial state.

---

# 17. Local Data Directory

WSM should use one stable application-data directory rather than storing data relative to whichever directory the user runs the command from.

For the MVP:

```text
~/.wsm/
```

is an acceptable cross-platform location.

Conceptual layout:

```text
~/.wsm/
├── active_session.json
└── sessions/
    ├── <uuid>.json
    ├── <uuid>.json
    └── ...
```

The required directories should be created automatically when needed.

---

# 18. Active Session Storage

The unfinished session is stored as:

```text
~/.wsm/active_session.json
```

The active-session file should store **events and timestamps**, not continuously updated duration counters.

Example active session:

```json
{
  "schema_version": 1,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Calculus Homework",
  "goal": "Complete problems 1-20",
  "started_at": "2026-09-08T19:42:00+00:00",
  "pauses": [
    {
      "started_at": "2026-09-08T20:13:00+00:00",
      "ended_at": null,
      "reason": "Lunch"
    }
  ]
}
```

There are intentionally no fields such as:

```text
current_timer
active_duration_seconds
paused_duration_seconds
```

in the unfinished session.

Those values can be derived from timestamps.

---

# 19. Determining Active vs Paused State

The runtime state can be derived from pause data.

The session is `PAUSED` when:

- at least one pause exists
- the most recent pause has:

```json
"ended_at": null
```

Otherwise the unfinished session is `ACTIVE`.

Completed sessions must never contain an unfinished pause.

---

# 20. Completed Session Storage

When finished, a session is written to:

```text
~/.wsm/sessions/<full-uuid>.json
```

Example:

```text
~/.wsm/sessions/550e8400-e29b-41d4-a716-446655440000.json
```

The UUID rather than the session name is used as the filename.

This prevents:

- duplicate filenames
- invalid filename characters
- problems caused by renaming sessions
- ambiguity between sessions with identical names

---

# 21. Completed Session JSON

Example:

```json
{
  "schema_version": 1,
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Calculus Homework",
  "goal": "Complete problems 1-20",

  "started_at": "2026-09-08T19:42:00+00:00",
  "ended_at": "2026-09-08T21:08:39+00:00",

  "active_duration_seconds": 4472,
  "paused_duration_seconds": 727,
  "total_duration_seconds": 5199,

  "pauses": [
    {
      "started_at": "2026-09-08T20:13:00+00:00",
      "ended_at": "2026-09-08T20:23:15+00:00",
      "duration_seconds": 615,
      "reason": "Lunch"
    },
    {
      "started_at": "2026-09-08T20:51:08+00:00",
      "ended_at": "2026-09-08T20:53:00+00:00",
      "duration_seconds": 112,
      "reason": "Bathroom"
    }
  ],

  "goal_completed": false,
  "notes": "Completed problems 1-16. Problems 17-20 took longer than expected."
}
```

The example timing is internally consistent:

```text
Total duration:
5199 seconds = 1:26:39

Paused:
615 + 112 = 727 seconds = 0:12:07

Active:
5199 - 727 = 4472 seconds = 1:14:32
```

---

# 22. Timestamp Authority

Persisted timestamps are the primary source of truth.

Final duration fields are derived values.

Conceptually:

```text
total_duration_seconds =
ended_at - started_at
```

```text
paused_duration_seconds =
sum(all pause intervals)
```

```text
active_duration_seconds =
total_duration_seconds - paused_duration_seconds
```

Future software modifying session timestamps should therefore recalculate derived durations.

Historical completed sessions are immutable in the MVP, so this issue does not currently arise.

---

# 23. Input Validation

The application must handle at least the following cases.

## Empty session name

Reject and request valid input.

## Empty goal

Reject and request valid input.

## Empty pause reason

Reject and request valid input.

## Invalid yes/no input

Request valid input again.

Accepted answers may include:

```text
y
yes
n
no
```

case-insensitively.

## Start while a session exists

Reject:

```text
A session is already in progress.
Finish the current session before starting another.
```

## Pause with no session

Reject.

## Pause while already paused

Reject.

## Resume with no session

Reject.

## Resume while already active

Reject.

## Finish with no session

Reject.

Normal invalid usage must not produce an unhandled exception.

---

# 24. System Clock Error Handling

Because WSM uses persisted system timestamps, impossible negative durations may indicate that the computer's clock was changed backward.

The application must not silently report negative work durations.

If:

```text
current timestamp < required previous timestamp
```

WSM should return a clear error indicating that the system clock appears inconsistent with stored session data.

---

# 25. Known Timing Limitation

Because WSM intentionally has no continuously running process or external time authority, it cannot completely protect against major manual changes to the computer's clock during a session.

Example:

```text
User starts session.
User manually changes system clock backward two hours.
User finishes session.
```

The calculated duration may be invalid.

Storing timestamps in UTC protects against timezone and daylight-saving-time changes, but it cannot determine the true elapsed time if the system clock itself has been deliberately changed.

This is an accepted MVP limitation.

---

# 26. Persistence Safety

Session state should be written safely.

When updating `active_session.json`, avoid leaving a partially written JSON file if possible.

A recommended pattern is:

1. write the new JSON to a temporary file
2. successfully close the temporary file
3. atomically replace the previous active-session file

When finishing a session:

1. construct the complete final session
2. successfully write the completed session file
3. only then remove `active_session.json`

If saving the completed session fails, the active-session file must not be deleted.

Preventing data loss is more important than clearing state prematurely.

---

# 27. CLI Help

The CLI should provide standard help information.

For example:

```bash
wsm --help
```

should show the available MVP commands:

```text
start
status
pause
resume
finish
```

Running:

```bash
wsm
```

without a command may display the same help information.

---

# 28. CLI Commands

The complete MVP command surface is:

```bash
wsm start
wsm status
wsm pause
wsm resume
wsm finish
```

No additional user-facing commands are required for MVP completion.

---

# 29. Testability Requirement

Timing logic must not require real waiting during automated tests.

Tests should never need logic such as:

```python
sleep(60)
```

to verify a one-minute session.

Access to the current time should therefore be centralized so tests can supply predetermined timestamps.

For example, production behavior might obtain:

```text
2026-09-08T19:00:00+00:00
```

while a test can explicitly provide:

```text
start = 19:00
pause = 19:30
resume = 19:40
finish = 20:00
```

and verify:

```text
total = 60 minutes
paused = 10 minutes
active = 50 minutes
```

The implementation does not need a complicated timing framework.

It only needs timing logic that can be tested deterministically.

---

# 30. Minimum Automated Test Coverage

Tests should cover at least:

- session creation
- UUID generation/preservation
- active duration without pauses
- one pause
- multiple pauses
- currently open pause
- finishing while active
- finishing while paused
- goal success `true`
- goal success `false`
- optional empty notes
- session persistence
- active-session recovery between commands
- invalid state transitions
- empty required input
- negative/impossible timestamp detection
- duration arithmetic

Python's built-in testing facilities are sufficient for MVP.

---

# 31. Session Lifecycle Example

A normal session might look like:

```text
$ wsm start

Session name: Calculus Homework
Goal: Complete problems 1-20

Session started.
```

Later:

```text
$ wsm status

Session: Calculus Homework
Goal: Complete problems 1-20
Status: ACTIVE

Active time: 00:31:15
Paused time: 00:00:00
Total elapsed: 00:31:15
```

Then:

```text
$ wsm pause

Why are you pausing? Lunch

Session paused.
```

The terminal can now be closed.

Later:

```text
$ wsm status

Session: Calculus Homework
Goal: Complete problems 1-20
Status: PAUSED

Active time: 00:31:15
Paused time: 00:17:44
Total elapsed: 00:48:59
```

Then:

```text
$ wsm resume

Session resumed.
```

Finally:

```text
$ wsm finish

Finish this session? [y/n]: y
Did you accomplish your goal? [y/n]: n
Notes (optional): Finished problems 1-16.

Session complete.

Session: Calculus Homework
Goal completed: No

Active time: 01:14:32
Paused time: 00:12:07
Total elapsed: 01:26:39
```

The session now exists permanently as:

```text
~/.wsm/sessions/<uuid>.json
```

and there is no unfinished active session.

---

# 32. Definition of MVP Completion

The MVP is complete only when this complete workflow reliably works:

1. Run `wsm start`.
2. Enter a valid name.
3. Enter a valid goal.
4. Generate a UUIDv4.
5. Record a UTC system timestamp.
6. Persist the unfinished session.
7. Exit the CLI completely.
8. Run `wsm status` later.
9. Correctly derive elapsed time from timestamps.
10. Pause the session.
11. Require and store a pause reason.
12. Exit the CLI again.
13. Correctly calculate an ongoing pause later.
14. Resume.
15. Finish the session.
16. Record yes/no goal completion.
17. Record optional notes.
18. Calculate final total time.
19. Calculate final paused time.
20. Calculate final active time.
21. Store the completed session using its UUID.
22. Remove the active-session state only after successful archival.
23. Inspect the JSON and verify all information is correct.
24. Start another session successfully.

The MVP is **not complete** merely because timing works.

The complete persistent session lifecycle must work.

---

# 33. Future Expansion

Structured JSON session data should make future versions capable of adding features such as:

```text
wsm history
wsm show <id>
wsm stats
```

Possible future functionality includes:

- session history
- filtering
- search
- projects
- categories
- weekly statistics
- monthly statistics
- goal completion rates
- pause analysis
- estimated versus actual work duration
- productivity patterns
- Markdown reports

These features are specifically excluded from the MVP.

The MVP architecture should allow them later without implementing them now.

---

# 34. MVP Product Identity

WSM should remain focused on:

> deliberate work sessions rather than passive time tracking

Its basic accountability loop is:

```text
Declare what you intend to accomplish
              ↓
             Work
              ↓
Account for interruptions
              ↓
Report whether the goal was achieved
              ↓
Preserve the record
```

The application should favor minimal friction, reliable local data, and explicit user intent over feature count.
