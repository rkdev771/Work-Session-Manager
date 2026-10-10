# 05: Close a PAUSED session safely

## What to build

A user can explicitly select and close a PAUSED session, including while a
different session is ACTIVE. Extend the established closing and recovery flow
to end its open pause correctly without affecting other sessions.

Specification: [WSM v0.1](../../specifications/WSM_V0_1_SPEC.md), sections
2–7 and 9.

## Blocked by

- 03: Pause, resume, and switch work deliberately.
- 04: Close an ACTIVE session safely.

## Acceptance criteria

- [ ] An explicit selector can close a PAUSED session; selector-free close
  continues targeting only the ACTIVE session, never guessing among pauses.
- [ ] Use the candidate close timestamp for both session end and its latest
  open pause end. Include the ongoing pause through that timestamp.
- [ ] CLOSED JSON has no open pauses and contains consistent session and
  individual pause durations, goal result, and notes.
- [ ] Closing PAUSED while another session is ACTIVE preserves that other
  session's data, state, and ongoing work.
- [ ] Reuse confirmation, retries, empty notes, cancellations, safe writes,
  selector invalidation, and final summary behavior from ACTIVE closing.
- [ ] Negative intervals, changed target data, failed saves, and cancelled
  input do not commit a partial closure or close a different session.
- [ ] Duplicate recovery accepts the verified completion of a PAUSED copy:
  prior history agrees, and the previously open pause ends at the archive's
  session end. Conflicting histories preserve both copies and fail clearly.
- [ ] A recovered session is CLOSED and unavailable through its old selector;
  it cannot be resumed or counted as ACTIVE.
- [ ] Overlapping resume/close operations preserve the newer valid state
  instead of overwriting it, and recovery cannot delete a changed copy.

## Public testing boundaries

Exercise selected PAUSED closure through the CLI and established public
timing/storage interfaces. Cover one/multiple pauses, both goal results,
empty notes, a different ACTIVE session, backward clocks, prompt cancellation,
save/cleanup failures, concurrent resume/close, and verified/conflicting paused
duplicates. Use supplied clocks and temporary data directories.

## Learning checkpoint

Explain why the open pause shares the close timestamp and why closing one
PAUSED session is independent of another session's work. Review the runnable
flow, diff, tests, and concerns before any commit.
