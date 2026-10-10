# 01: Create and select saved sessions

## What to build

A user can create sessions, exit WSM, and list them in another command to
obtain compact numeric selectors. Preserve the existing model and CLI skeleton.
Introduce only the storage and input behavior needed for this complete flow.

Specification: [WSM v0.1](../../specifications/WSM_V0_1_SPEC.md), sections
1–4, 6–7, and 9–10.

## Blocked by

None (can start when the user agrees to begin this ticket).

## Acceptance criteria

- [ ] Create requires title and goal, trims surrounding whitespace, retries
  blank input, generates a UUIDv4, and saves a CREATED record immediately.
- [ ] Duplicate titles are allowed. CREATED JSON has no start timestamp,
  pauses, closing data, duration counters, or duplicated state.
- [ ] Ctrl-C or end-of-input during either prompt reports cancellation and
  persists none of the proposed session data.
- [ ] Stable local storage is independent of the current working directory;
  needed directories are created automatically.
- [ ] Unfinished records are UUID-named JSON files. Updates use temporary
  writes and atomic replacement; failed saves do not destroy valid records
  or falsely report success.
- [ ] Default listing shows unfinished title, state, and compact selectors,
  alphabetically ordered by title with UUID breaking identical-title ties.
- [ ] Each successful listing safely persists its number-to-UUID mapping;
  an empty inventory produces a clear message and empty mapping.
- [ ] Creation leaves the old mapping unchanged and directs the user to list
  sessions. The mapping survives independent command executions.
- [ ] A listing can rebuild a missing or damaged selector mapping without
  changing session identities or guessing previous numbers.
- [ ] Malformed session data, unsupported schema versions, identity/filename
  mismatches, and invalid structural values produce clear file-specific
  errors without silently skipping or rewriting records.
- [ ] Brief storage coordination prevents concurrent creation and listing
  from losing records or corrupting the saved selector mapping. Prompts do
  not hold exclusive storage access.
- [ ] Existing CLI/model behavior and tests are preserved; incidental
  deserialization exceptions are handled cleanly at the public boundary.

## Public testing boundaries

Agree on the small public storage interface before adding tests. Exercise
creation and default listing through the CLI, round trips through public
model methods, and persistence/failures through that storage interface.
Use temporary data directories and separate processes for persistence checks.
Verify invalid JSON shapes, duplicate titles, cancellation, damaged mapping,
atomic-write failures, and overlapping creates/listings without coupling tests
to private helpers. Use standard-library unittest.

## Learning checkpoint

Explain the data directory, the storage interface, meaningful storage
alternatives, atomic replacement, and the distinction between a selector and
a UUID. Review the runnable flow, diff, tests, and concerns before any commit.
