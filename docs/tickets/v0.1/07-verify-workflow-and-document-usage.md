# 07: Verify the complete workflow and document usage

## What to build

Demonstrate the complete persistent multi-session accountability loop across
independent CLI executions, resolve integration defects, and give the user
clear installation and usage instructions. Earlier tickets already include
their own tests; this ticket verifies how the completed flows work together.

Specification: [WSM v0.1](../../specifications/WSM_V0_1_SPEC.md), especially
sections 8–10 and the complete lifecycle in section 9.

## Blocked by

- 05: Close a PAUSED session safely.
- 06: Include CLOSED sessions with --all.

## Acceptance criteria

- [x] Demonstrate create, list, start, status, pause, start another session,
  pause/close it, resume the earlier session, and close it across separate
  processes without a running timer or real waiting in tests.
- [x] Verify compact selector refresh after closures, unavailable old numbers,
  unnumbered newly created sessions, duplicate titles, and --all records
  without selectors. Both forms rebuild the same unfinished mapping.
- [x] Inspect resulting JSON for UUIDv4 identity, schema version, whole-second
  UTC events, derived state, event-only unfinished data, closed pauses,
  correct final durations, goal accountability, and optional empty notes.
- [x] Cross-flow invalid transitions, cancellations, clock errors, malformed
  stores/mappings, failed writes, interrupted closing, and conflicting copies
  report clear outcomes without destroying data or applying invalid changes.
- [x] Separate-process concurrency verifies the single-ACTIVE invariant,
  safe selector refresh, and rejection of changed sessions during pending
  prompts. Fix integration defects within the approved requirements.
- [x] Test local start display, fixed active time while paused, durations
  exceeding 24 hours, empty-store output, and help for the complete command
  surface. Avoid repeating already sufficient tests solely for coverage counts.
- [x] Document Python support, installation, both entry points, the amended
  workflow, selector refresh semantics, the local data directory, timestamp
  timing, and the accepted manual-clock limitation.
- [x] Documentation clearly states v0.1 exclusions. No speculative features,
  runtime dependencies, tracker setup, or whole-spec implementation tooling
  are introduced.
- [x] Run the full existing and new unittest suite, review completed behavior
  against the approved specification, and resolve material review findings
  before declaring v0.1 complete.

## Public testing boundaries

Use CLI subprocesses for the integration workflow and concurrency cases, with
temporary storage and supplied deterministic times. Retain public model,
timing, and storage tests from earlier tickets. Confirm the final checks fit
the documented interfaces without adding a product-facing test clock flag,
configuration system, or real-time sleeps.

## Learning checkpoint

The user should be able to explain the CLI, model, selector mapping, storage,
time calculations, lifecycle checks, and archival/recovery flow. Present the
full verification result and remaining limitations. Review the final diff and
wait for explicit commit approval before committing.
