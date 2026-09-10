# WSM v0.1 Multi-Session Amendment

## Purpose

This document is an official amendment to the frozen WSM v0.1 MVP specification.

It defines how WSM handles multiple saved sessions, session selection, session states, and commands that operate on specific sessions.

This amendment should be treated as authoritative alongside `MVP.md`.

---

## Core Multi-Session Rule

WSM may store any number of sessions, but at most one session may be actively running at any given time.

Valid example:

- Calculus Homework — ACTIVE
- WSM Development — PAUSED
- Essay Draft — CREATED
- Astronomy Reading — CLOSED

Invalid example:

- Calculus Homework — ACTIVE
- WSM Development — ACTIVE

If the user attempts to start or resume a session while another session is already ACTIVE, the command must fail and no session state may change.

WSM must not automatically pause the currently active session.

---

## Session States

Every session must exist in one of four states:

- `CREATED`
- `ACTIVE`
- `PAUSED`
- `CLOSED`

### CREATED

The session exists but has never been started.

### ACTIVE

The session is currently accumulating work time.

Only one session may be ACTIVE at a time.

### PAUSED

The session has been started previously but is not currently accumulating work time.

Any number of sessions may be PAUSED simultaneously.

### CLOSED

The session has been completed and is no longer editable through normal session lifecycle commands.

`CLOSED` is a terminal state for v0.1.

---

## Valid State Transitions

The following transitions are valid:

    CREATED -> ACTIVE
        start

    ACTIVE -> PAUSED
        pause

    PAUSED -> ACTIVE
        resume

    ACTIVE -> CLOSED
        close

    PAUSED -> CLOSED
        close

The session lifecycle is:

    CREATED
       |
       | start
       v
    ACTIVE <------+
       |          |
       | pause    | resume
       v          |
    PAUSED -------+
       |
       | close
       v
    CLOSED

An ACTIVE session may also transition directly to CLOSED using `close`.

---

## Invalid State Transitions

Invalid lifecycle operations must return a clear error and must not modify session state.

Examples:

    start ACTIVE
    -> Error: Session has already started.

    start PAUSED
    -> Error: Session has already started. Use resume instead.

    resume CREATED
    -> Error: Session has not been started yet.

    resume ACTIVE
    -> Error: Session is already active.

    pause PAUSED
    -> Error: Session is already paused.

    pause with no ACTIVE session
    -> Error: No active session.

    close CLOSED
    -> Error: Session is already closed.

Starting or resuming any session while another session is ACTIVE must also fail.

Example:

    [1] WSM Development — ACTIVE
    [2] Calculus Homework — CREATED

    > start 2

    Cannot start "Calculus Homework".

    "WSM Development" is currently active.
    Pause or close the active session first.

No automatic pause should occur.

---

## Session Selection

WSM must provide a human-friendly way to select specific sessions.

Users should not be required to type UUIDs during normal CLI use.

Internally, UUIDs remain the permanent identifiers for sessions.

The CLI may display temporary numeric selectors.

Example:

    > sessions

    [1] WSM Development
        Status: ACTIVE
        Goal: Implement JSON persistence

    [2] Calculus Homework
        Status: PAUSED
        Goal: Complete problems 1-20

    [3] Essay Draft
        Status: CREATED
        Goal: Write introduction

The user can then reference a session using the displayed selector.

Example:

    > resume 2

The CLI should resolve the selector to the correct internal UUID.

Numeric selectors are only display and interaction conveniences. They must not replace UUIDs as the persistent session identity.

---

## Commands

The exact CLI parsing structure may evolve during implementation, but v0.1 must support the following behavior.

### create

Creates a new session.

Creating a session does not automatically start it.

Example:

    > create

    Title: WSM Development
    Goal: Implement multi-session behavior

    Session created.

The new session begins in the `CREATED` state.

---

### sessions

Displays saved sessions in a form that allows the user to identify and select them.

Minimum information should include:

- temporary selector
- session title
- session state

The goal may also be displayed if useful.

Example:

    > sessions

    [1] WSM Development      ACTIVE
    [2] Calculus Homework    PAUSED
    [3] Essay Draft          CREATED
    [4] Astronomy Reading    CLOSED

Filtering, sorting options, pagination, and advanced display controls are outside the v0.1 scope.

---

### status

Displays information about the currently ACTIVE session.

If a session is ACTIVE, the output should include useful information such as:

- title
- goal
- start time
- current calculated work duration

Example:

    > status

    ACTIVE SESSION

    WSM Development
    Goal: Implement multi-session behavior
    Started: 2:10 PM
    Elapsed work: 42m

This does not require a continuously updating timer.

Elapsed time should be calculated from timestamps when the command is executed.

If there is no ACTIVE session, `status` should report that clearly.

Example:

    > status

    No active session.
    2 paused sessions.
    1 unstarted session.

---

### start <session>

Starts a session currently in the `CREATED` state.

Example:

    > start 3

Before starting the selected session, WSM must verify that no other session is ACTIVE.

If another session is ACTIVE, the command must fail.

---

### pause

Pauses the currently ACTIVE session.

Because WSM allows only one ACTIVE session, no session selector is required.

Example:

    > pause

    Reason: Getting food

    Session paused.

The pause reason and timestamp behavior remain consistent with the original MVP specification.

If no session is ACTIVE, the command must fail.

---

### resume <session>

Resumes a specific PAUSED session.

Example:

    > resume 2

Before resuming, WSM must verify that no other session is ACTIVE.

If another session is ACTIVE, the command must fail.

---

### close [session]

Closes a work session.

If no selector is supplied, `close` may operate on the currently ACTIVE session.

Example:

    > close

If the user wants to close a PAUSED session, they must identify the session.

Example:

    > close 2

Closing a session must retain the existing v0.1 close workflow:

    Successful? [y/n]:
    Notes (optional):

The session then transitions to `CLOSED`.

A `CREATED` session should not be closed in v0.1 because it has never been started.

Deletion or cancellation of unstarted sessions is outside the scope of this amendment.

---

## Time Tracking

This amendment does not change the original timestamp-based timing architecture.

WSM must not maintain a continuously running timer as the source of truth.

Work duration is still calculated using stored timestamps:

    work duration =
        stop/current time
        - start time
        - total paused duration

The `status` command may calculate and display current elapsed work time while a session is ACTIVE.

This calculation is only a display operation and does not change the underlying timestamp-based design.

---

## v0.1 Interface Boundary

This amendment does not add a TUI.

WSM v0.1 remains a text-based CLI.

The following are outside the v0.1 scope:

- continuously updating live timer
- terminal dashboard
- progress bars
- graphical terminal widgets
- mouse interaction
- full-screen TUI
- advanced session filtering
- automatic session switching

These may be considered for later versions.

---

## Required Invariants

The implementation must preserve the following rules:

1. Every session has exactly one lifecycle state.
2. At most one session may be `ACTIVE`.
3. Any number of sessions may be `CREATED`, `PAUSED`, or `CLOSED`.
4. Starting or resuming a second session while another is ACTIVE must fail.
5. Invalid commands must not modify stored session state.
6. UUIDs remain the permanent internal session identifiers.
7. Human-friendly selectors may be used for CLI interaction.
8. Timing remains timestamp-based.
9. `CLOSED` sessions cannot return to another state in v0.1.
10. Creating a session does not automatically start it.

---

## Relationship to MVP.md

This document does not replace `MVP.md`.

It extends the v0.1 specification by resolving previously undefined multi-session behavior.

If this document conflicts with an older assumption about multi-session behavior, this amendment takes precedence for that specific behavior.

All unrelated requirements in `MVP.md` remain unchanged.
