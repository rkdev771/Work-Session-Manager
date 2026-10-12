# 06: Include CLOSED sessions with --all

## What to build

A user can explicitly include CLOSED records in the session listing without
giving them lifecycle selectors. Either listing refreshes the same compact
unfinished-session mapping.

Specification: [WSM v0.1](../../specifications/WSM_V0_1_SPEC.md), sections
3.2, 6–9.

## Blocked by

- 01: Create and select saved sessions.

Existing CLOSED model records can be used as fixtures, so implementing close
is not a prerequisite. Use the existing public storage/listing boundary;
timing validation added by ticket 02 continues to apply when integrated.

## Acceptance criteria

- [ ] Command help documents sessions --all. No additional filtering,
  sorting options, pagination, or separate history command is introduced.
- [ ] Default listing excludes CLOSED sessions.
- [ ] The --all listing appends CLOSED title/state entries after unfinished
  sessions. CLOSED entries have no numeric selectors and consume no numbers.
- [ ] Both listing forms refresh and persist identical compact unfinished
  selectors over the same inventory, including an empty unfinished inventory.
- [ ] Existing mapping holes and newly unnumbered sessions are handled by
  rebuilding from current unfinished records rather than preserving old gaps.
- [ ] Duplicate titles across unfinished and CLOSED records remain allowed;
  CLOSED records cannot become lifecycle targets through the mapping.
- [ ] Listing does not edit CLOSED records. Malformed records still fail
  clearly rather than being silently skipped, even when default display hides
  CLOSED entries.
- [ ] Listing respects shared storage coordination; a refresh cannot silently
  retarget a command that has already resolved its selected UUID.

## Public testing boundaries

Exercise argument parsing and CLI listings with the public storage interface
and valid CLOSED fixtures. Verify mixed and all-CLOSED inventories, duplicate
titles, identical mappings from both forms, persisted mapping between processes,
and no CLOSED record mutation. Do not depend on private presentation helpers
or require a completed close command to build this slice.

## Learning checkpoint

Explain why both displays share a selector refresh and why CLOSED entries do
not consume numbers. Review the runnable flow, diff, tests, and concerns before
any commit.
