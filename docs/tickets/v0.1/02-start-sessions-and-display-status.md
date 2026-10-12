# 02: Start sessions and display status

## What to build

A user can start a selected CREATED session, exit WSM, and later see correct
ACTIVE status calculated from saved whole-second UTC timestamps. Invalid
transitions and clock problems leave session data unchanged.

Specification: [WSM v0.1](../../specifications/WSM_V0_1_SPEC.md), sections
2–7 and 9–10.

## Blocked by

- 01: Create and select saved sessions.

## Acceptance criteria

- [ ] Numeric selection resolves through the latest persisted listing to a
  UUID. Missing, invalid, nonpositive, unknown, or unavailable selectors
  fail clearly; absent/damaged mappings request a fresh listing.
- [ ] Start accepts only CREATED sessions, rejects already started or CLOSED
  targets, and directs PAUSED targets to resume.
- [ ] Check that no other session is ACTIVE before capturing the transition
  timestamp and saving. The check/save operation remains valid when commands
  overlap; simultaneous starts cannot leave two ACTIVE sessions.
- [ ] Centralized clock access supplies timezone-aware UTC values with
  fractional seconds discarded at capture. Tests can supply times without
  real waiting. Start time excludes create prompt entry.
- [ ] Start persists event data without duration counters or duplicated state
  and reports success only after saving.
- [ ] Public timing behavior calculates total, paused, and active seconds
  from timestamps, including ended and open pauses, without a running timer.
- [ ] Validate whole-second timestamp precision, chronology, pause ordering
  and overlap, required previous-event clock comparisons, and derived CLOSED
  duration consistency. Equal timestamps and zero intervals are valid.
- [ ] Invalid stored timing is reported separately from a current-clock
  inconsistency. Do not clamp or round away invalid intervals.
- [ ] Status shows ACTIVE title, goal, state, local start date/time, active
  time, paused time, and total elapsed as HH:MM:SS, with hours above 24 intact.
- [ ] With no ACTIVE session, status reports that fact and PAUSED/CREATED
  counts. Multiple stored ACTIVE sessions stop the operation clearly.
- [ ] Start/status do not refresh selectors. Resolving a target once must
  not allow another listing to silently retarget an in-progress operation.
- [ ] Full storage loading incorporates timing validation without treating
  intentionally incomplete structural-test fixtures as valid timed records.

## Public testing boundaries

Agree on the public clock/timing seam before adding tests. Test deterministic
interval arithmetic and validation there, and start/status through the CLI and
the established public storage interface. Cover a separate-process restart,
overlapping starts, invalid selections/transitions, backward clocks, local
display, large hour values, and unchanged files on failures. Retain existing
structural model coverage; do not test private timing helpers.

## Learning checkpoint

Explain supplied clocks, UTC storage versus local display, deriving state,
timestamp subtraction, and why checking before saving must be coordinated.
Review the runnable flow, diff, tests, and concerns before any commit.
