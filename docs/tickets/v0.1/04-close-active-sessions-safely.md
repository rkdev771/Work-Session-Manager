# 04: Close an ACTIVE session safely

## What to build

A user can close an ACTIVE session with confirmation, goal accountability,
optional notes, and correct final durations. Archival and interrupted cleanup
preserve data. This slice handles ACTIVE closure; ticket 05 adds PAUSED closure.

Specification: [WSM v0.1](../../specifications/WSM_V0_1_SPEC.md), sections
2–7 and 9.

## Blocked by

- 02: Start sessions and display status.

## Acceptance criteria

- [ ] Close without a selector targets the ACTIVE session; an explicit
  selector may identify it. Reject no-target, CREATED, and unavailable/CLOSED
  selections clearly without changing the requested session state.
- [ ] Capture the whole-second candidate end time at command initiation,
  identify the target, and prompt for confirmation, goal completion, and notes.
- [ ] Accept case-insensitive y/yes/n/no and retry invalid answers. A no
  confirmation or Ctrl-C/EOF at any prompt discards all proposed closing data.
- [ ] Prompt retries retain the original candidate timestamp. Empty notes and
  both boolean goal results are supported; partial achievement is no.
- [ ] Construct and validate a complete CLOSED record using the candidate
  end time and timestamp-derived integer durations before saving it.
- [ ] Save the UUID-named archive safely before removing the unfinished
  copy. Archive failure preserves unfinished state. Never overwrite an
  existing CLOSED record with a new lifecycle result.
- [ ] Successful close reports title, goal completion, and all three final
  durations. Its number becomes unavailable without reassigning other numbers.
- [ ] Inventory scanning notices duplicate unfinished/CLOSED UUIDs. Only
  duplicates trigger deeper comparison in the shared storage layer.
- [ ] A valid archive matching the ACTIVE unfinished copy's identity, title,
  goal, start timestamp, and prior pause history is authoritative. Safely
  remove the leftover unfinished copy without resurrecting that session.
- [ ] Conflicting copies remain untouched and produce a clear error. Cleanup
  failure preserves the archive and does not falsely report successful cleanup.
- [ ] Before committing pending answers, recheck the target and invariants.
  A changed target fails rather than overwriting newer state; prompts do not
  hold exclusive access. Concurrent closes cannot overwrite an archive or
  remove a changed unfinished copy.

## Public testing boundaries

Use CLI, public timing, and public storage boundaries with deterministic
timestamps. Cover confirmation refusal, invalid answers, both goal results,
empty notes, all prompt cancellations, conflicting commands, failed archive
saves, failed cleanup, and duplicate-copy recovery across command executions.
Failure injection at the storage boundary must verify archive-before-cleanup
ordering and preserved files, without mirroring private helper steps.

## Learning checkpoint

Explain candidate end times, constructing a final record before saving,
archive-before-cleanup ordering, and conditional recovery from a completed
save. Review the runnable flow, diff, tests, and concerns before any commit.
