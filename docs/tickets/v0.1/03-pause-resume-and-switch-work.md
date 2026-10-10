# 03: Pause, resume, and switch work deliberately

## What to build

A user can pause the ACTIVE session with a required reason, work on another
saved session, and later resume the chosen PAUSED session. Pauses survive
terminal closure and concurrent prompt activity cannot overwrite newer state.

Specification: [WSM v0.1](../../specifications/WSM_V0_1_SPEC.md), sections
2–7 and 9.

## Blocked by

- 02: Start sessions and display status.

## Acceptance criteria

- [ ] Pause targets the sole ACTIVE session without a selector and fails
  clearly when none exists.
- [ ] Capture a whole-second candidate pause time at command initiation,
  before prompting. Require a trimmed nonblank reason; retries retain that
  same candidate time.
- [ ] Successful pause saves an interval with a null end timestamp. All
  unfinished pause JSON remains event-only, including previously ended pauses.
- [ ] Ctrl-C/EOF during the reason prompt discards the candidate and leaves
  the proposed pause uncommitted.
- [ ] Resume resolves a selected PAUSED session and ends its latest open
  pause at a timestamp captured after validation and the no-ACTIVE check.
- [ ] Resume rejects CREATED, ACTIVE, CLOSED, and unavailable targets.
  Starting/resuming a second session while one is ACTIVE changes no sessions.
- [ ] Multiple PAUSED sessions are supported; a CREATED session can start
  when the earlier ACTIVE session has been paused. Creation itself remains
  permitted while another session is ACTIVE.
- [ ] Repeated pauses/resumptions and ongoing pauses produce correct timing;
  active duration stays fixed while a session remains PAUSED.
- [ ] Backward clock values, failed saves, and invalid transitions leave the
  requested state unchanged and produce clear errors.
- [ ] Exclusive storage access is not held during prompts. If another
  command changes the selected session, reject the pending pause save rather
  than overwriting newer state. Concurrent resumes/starts preserve one ACTIVE.
- [ ] Pause/resume do not refresh selectors or silently retarget a UUID
  already selected when another listing occurs.

## Public testing boundaries

Use public CLI, timing, and storage interfaces with supplied clocks and
temporary data directories. Verify prompt retries/cancellation, timestamp
placement, multiple pause intervals, separate-process recovery, switching
between sessions, and conflicting operations during a pending prompt. Test
coordination through externally visible saved state, not lock implementation.

## Learning checkpoint

Explain open intervals, why pause captures time before input, how a paused
session's active time stays fixed, and checking for changed data before saving.
Review the runnable flow, diff, tests, and concerns before any commit.
