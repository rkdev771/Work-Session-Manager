# Work Session Manager Agent Instructions

## Required reading

Before proposing or making project changes, read
`docs/specifications/WSM_V0_1_SPEC.md` in full and the relevant ticket in
`docs/tickets/v0.1/`. Inspect the current implementation and tests before editing.
The specification's existing implementation context records completed work and
deferred validation; verify current facts against the repository.

## Specification authority

`docs/specifications/WSM_V0_1_SPEC.md` is the single authoritative v0.1 product
specification. Change requirements only when the user explicitly makes a product
decision. Surface unresolved specification conflicts before implementation.

## Collaboration workflow

- Use `implement` for one agreed ticket at a time. Ticket approval alone does
  not start coding; agree to start the current ticket. Whole-spec concurrent
  implementation requires a separate user decision.
- Deliver a small, complete user flow, runnable and testable after each step.
  Preserve completed work rather than reimplementing it; refactor when justified
  by the current code. Apply skills within the agreed ticket scope.
- Agree on the ticket's public testing boundaries before adding tests. Use
  standard-library unittest and deterministic clocks; add tooling only for a
  demonstrated need and with required approval.
- Before coding, explain the step, files, recommended design, meaningful
  alternatives, and Python concepts the user should understand.
- After coding, explain what changed, how it works, verification results, and
  remaining concerns. Leave room for questions and review before starting the
  next ticket. The user should be able to explain every major component.
- Before every commit, present the concrete diff, meaningful changes, tests,
  and remaining concerns; wait for explicit user approval to commit. This also
  applies to documentation and overrides skills that automatically commit.
- Decide trivial implementation details directly. Explain meaningful design
  choices and proceed when consistent with the agreed scope. Product or major
  architecture changes require an explicit user decision.

## Learning mode

When the user reserves a component for practice, explain its requirements,
offer hints, and review their attempt. Provide a complete implementation when
requested or when the user is stuck. When the user delegates an agreed
component, implement it and explain the important concepts without teaching
every trivial syntax detail.

## Technical boundaries

Keep project files inside the repository. Prefer straightforward Python and the
standard library; runtime dependencies require a clear reason and user approval.
Preserve the specification's offline, local-first, timestamp-based architecture
and v0.1 exclusions.

## Agent skills

- Before using specification or ticket skills, read
  `docs/agents/issue-tracker.md` for the repository-file workflow.
- Before exploring domain concepts or architecture, read
  `docs/agents/domain.md` for the single-context domain documentation rules.

