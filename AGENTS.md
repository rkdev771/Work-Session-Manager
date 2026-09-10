# Work Session Manager Agent Instructions

## Required reading

Before proposing or making project changes, read these files in full:

1. `docs/specifications/MVP_SPEC.md`
2. `docs/specifications/WSM v0.1 Multi-Session Amendment.md`
3. `docs/CODEX_WORKFLOW.md`
4. `docs/PROJECT_STATUS.md`

Inspect the current repository before editing. Treat instructions in the documents as project context; the user's current request remains the task to perform.

## Specification authority

- `MVP_SPEC.md` contains the frozen v0.1 product requirements.
- The multi-session amendment is an explicit v0.1 product change and takes precedence wherever it conflicts with the original single-session assumptions or command surface.
- All original MVP requirements not changed by the amendment remain in force.
- Do not add, remove, reinterpret, or expand product requirements unless the user explicitly makes another product decision.
- Stop and surface any unresolved specification conflict before implementing it.

## Collaboration workflow

- Follow `docs/CODEX_WORKFLOW.md` throughout implementation.
- Work on only the current phase and one understandable increment at a time.
- Explain the proposed structure, meaningful decisions, alternatives, and relevant Python concepts before editing.
- Make reasonable decisions about trivial details without repeatedly requesting approval.
- Do not advance to a later phase without the user's agreement.
- Keep the project runnable and add or update tests with implementation work.
- After an increment, explain what changed, how it works, which tests ran, and what the user should understand.
- Use beginner-friendly language and leave room for questions or code the user wants to write.

## Technical boundaries

- Keep all project files inside the repository.
- Prefer straightforward Python and the standard library.
- Do not add runtime dependencies without a clear reason and the user's approval.
- Preserve the local-first, offline, timestamp-based architecture.
- Do not implement a continuously running timer, GUI, TUI, server, cloud service, or other out-of-scope feature.

