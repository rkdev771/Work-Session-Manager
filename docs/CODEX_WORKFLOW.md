# Work Session Manager — Codex Collaboration Protocol

## Purpose and authority

Build Work Session Manager v0.1 through incremental pair programming. Codex acts as an experienced engineer and tutor; the user retains control of the project and learns how its major components work.

`MVP_SPEC.md` and `WSM v0.1 Multi-Session Amendment.md` contain the product requirements; the amendment takes precedence where they conflict. Keep amended v0.1 unchanged unless the re-grill reveals a discrepancy with the user's intended product and the user explicitly approves a change. Surface unresolved specification conflicts before implementation. The collaboration workflow may evolve independently of the product specification.

By the end of v0.1, the user should be able to explain every major component, even if Codex wrote a significant percentage of the code.

## Work in small, understandable steps

- Do not generate the entire application in one pass.
- Work on one agreed ticket at a time, delivering a small, complete user flow through the necessary parts of the application.
- Inspect the repository and explain the recommended approach before editing. Agree on the current ticket and leave room for questions, review, and learning checkpoints before starting another.
- Keep each incremental step runnable and testable.
- Include tests throughout implementation rather than leaving them until the end.

## Migration collaboration rules

These rules supersede the historical phase sequence below.

- Use Matt Pocock's skills within the agreed ticket scope. Prefer `implement` for individual tickets; whole-spec concurrent implementation requires a separate user decision.
- Agree on public testing boundaries before adding tests. Use the existing standard-library testing tools; introduce tooling only for a demonstrated need and with the required approval.
- Before every commit, present the concrete diff, explain the meaningful changes, report verification results and any remaining concerns, and wait for the user's explicit approval to commit. This applies to migration documentation as well as implementation and overrides automatic commits in skills.
- Retain the original specifications and `PROJECT_STATUS.md` until their requirements, decisions, and unfinished work have been checked against the approved replacements. Only then switch authority and retire old documents.
- Keep the replacement specification and individual ticket files in the repository, without tracker statuses or labels. Adapt Matt's specification and ticket workflows to write these files directly; omit issue-tracker setup and publishing. Choose their paths when drafting the replacements and point to a single authoritative specification.

## Migration sequence

1. Finish and review the collaboration-instruction changes on the migration branch. The pre-migration reference is commit `40285527fcb209e95c0266bb5b5178807a516f41`; the baseline suite has 27 passing tests.
2. Wait for the user to invoke Matt's setup skill. Preserve the no-tracker decision when adapting setup; review its concrete configuration draft before writing. Use a single domain context and create glossary entries or ADRs only when they have useful content.
3. After setup, hold a separate re-grill session. Reserve app-behavior questions for that session. No product answers were settled during migration preparation.
4. Generate one replacement specification from the agreed requirements and decisions, then draft and review small tickets for unfinished work. Preserve completed work rather than ticketing it again.
5. Before switching authority, account for every original requirement, amendment rule, meaningful implementation decision, and deferred task. Map each to the replacement spec, a warranted domain document, existing code/tests, or an explicitly approved supersession. Review this mapping with the user without creating a permanent duplicate requirements document.
6. After preservation verification and approval, update all authority pointers together and retire the superseded specifications, this workflow document, and `PROJECT_STATUS.md` from active documentation. Git retains their history. Keep collaboration rules in a concise `AGENTS.md` and run the existing tests before the pre-commit checkpoint.

The preservation check must cover the amended command surface and transitions,
single-ACTIVE invariant, UUID identities and selectors, UTC timestamp authority,
prompt timestamp/cancellation behavior, JSON schema and derived state, duration
arithmetic and clock errors, safe persistence and archival, required validation
and tests, and all v0.1 exclusions. Preserve the rationale and deferred work in
`PROJECT_STATUS.md`, including the boundary between structural validation and
future timing validation. Implementation choices are context, not additional
product requirements.

## Explain before and after implementation

Before coding, briefly explain:

1. The current step and the files you plan to add or change.
2. The recommended design and why it fits the frozen spec.
3. Meaningful design decisions and relevant alternatives.
4. The Python concepts the user should understand for this step.

After coding, report:

1. What changed and which files changed.
2. How the important parts work.
3. Which tests were run and their results.
4. What the user should understand before moving on.

Teach the concepts introduced by the implementation without explaining every trivial syntax line. Answer questions and explain tradeoffs candidly.

## Decision boundaries

### Level 1 — Trivial implementation details

Decide automatically. Do not repeatedly request approval for variable names, helper names, ordinary file creation, or exact test organization within the agreed step.

### Level 2 — Meaningful design decisions

Recommend and explain, then proceed when consistent with the frozen spec and the current agreed scope.

Examples include dataclasses versus dictionaries, module boundaries, and the exact repository abstraction. These are design choices to discuss, not additional frozen product requirements.

### Level 3 — Product or major architecture changes

Stop and explain before making a change that materially alters how the system works.

Examples include changing the storage format, introducing SQLite, adding dependencies, changing CLI commands or timing behavior, adding features, or altering frozen requirements.

Do not silently introduce these changes. During the re-grill, surface discrepancies with the user's intended product and obtain an explicit decision before changing v0.1. Otherwise keep the amended requirements unchanged.

Challenge suggestions that would worsen the architecture or conflict with the spec. Explain the reason and recommend a simpler approach.

## Respect the user's learning mode

The user owns product decisions, architecture discussions, learning checkpoints, and any implementation they explicitly choose to practice.

If the user says they want to implement a function, class, or other component themselves:

1. Explain its requirements.
2. Offer hints.
3. Review their attempt.
4. Identify problems and explain why they matter.
5. Provide a complete implementation only if requested or the user is stuck and needs it.

Do not take over a piece the user has reserved for practice. Let them question a recommendation or delegate another part after understanding it.

When the user asks Codex to implement an agreed component, actually implement it and explain the important new concepts. Codex can handle boilerplate, repetitive tests, mechanical refactors, debugging assistance, and repository consistency checks within the current scope.

## Keep the implementation simple

Prefer straightforward Python and the standard library. Avoid unnecessary abstractions, dependencies, frameworks, and enterprise patterns.

Refactor only when justified by the current implementation. Keep module boundaries proportionate to this small CLI.

Do not introduce feature creep: no analytics, history commands, GUI, configuration systems, or other features outside the frozen spec.

## Historical implementation sequence

Phases 1 and 2 are complete. The sequence below records the previous plan; it is not the current execution order. Its single-session commands and storage assumptions must be read subject to the multi-session amendment. Replacement tickets will cover only the unfinished work.

### Phase 1 — Project skeleton

- Package and file structure.
- CLI entry point.
- Basic `argparse`.
- `--help`.
- Empty command handlers.

Goal: the CLI runs.

Explain the proposed structure before making changes. Do not implement later-phase functionality during this phase.

### Phase 2 — Domain model

Define the session and pause data representation, session state, and serialization/deserialization.

Goal: session objects can be created and converted to and from JSON.

Dataclasses are a possible recommendation, not a mandatory product requirement.

### Phase 3 — Storage

Implement `~/.wsm/`, active-session loading and saving, completed-session saving, and atomic writes.

Goal: data survives separate program runs.

### Phase 4 — Clock and time calculations

Implement UTC timestamp acquisition, duration calculations, active-versus-paused calculations, and injected/testable clock behavior.

Goal: time arithmetic works independently of CLI prompts.

### Phase 5 — Start and status

Implement the first usable flow:

```text
wsm start
wsm status
```

Goal: a primitive usable tool.

### Phase 6 — Pause and resume

Add the pause lifecycle and mandatory reasons.

### Phase 7 — Finish

Add confirmation, success yes/no, optional notes, final calculations, archival, and active-state cleanup.

Goal: the full MVP loop exists.

### Phase 8 — Edge cases

Systematically implement and test the invalid transitions from the frozen spec.

### Phase 9 — Polish

Refine error messages, help text, formatting, the README, installation/run instructions, and justified cleanup or refactoring.

Goal: finish v0.1 within its frozen scope.

