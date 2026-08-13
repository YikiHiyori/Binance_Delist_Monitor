# Workflow

This file defines the end-to-end task lifecycle for this repository and any future work that reuses it.
Future runs should skim `agents.md`, this file, `LESSONS.md`, and the recent entries in `TASK_LOG.md` before starting any non-trivial task.

## Lifecycle

1. Intake the request and restate the goal in plain language.
2. Classify complexity as trivial, normal, complex, or high-risk.
3. Read prior lessons and the latest relevant task log entries.
4. Select the smallest useful set of subagents.
5. Draft a task plan with assumptions, risks, dependencies, and validation steps.
6. Execute in small change sets.
7. Validate against the plan before claiming completion.
8. Document any user-facing or process changes.
9. Reflect on errors, false assumptions, and reusable lessons.
10. Update durable memory files when a lesson is broadly reusable.

## Complexity Branching

### Trivial

- Use a minimal path.
- Still skim `agents.md`, `WORKFLOW.md`, `LESSONS.md`, and recent `TASK_LOG.md` entries.
- Skip formal subagent decomposition unless the task unexpectedly expands.
- If anything surprising happens, record a short reflection in `TASK_LOG.md`.

### Normal

- Write a compact plan before editing.
- Use subagents when the work has separable research, implementation, review, or validation steps.
- Require at least one explicit validation step before finalizing.

### Complex

- Require subagent decomposition before implementation starts.
- Require a validation plan before code or content changes.
- Require reviewer and validator passes before final sign-off.

### High-Risk

- Write explicit assumptions and rollback thinking before changes.
- Prefer staged changes over broad edits.
- Require test evidence or equivalent verification before completion.

## Validation-First Rules

- Do not claim completion until the intended behavior has been checked.
- Separate implementation from validation so failures are visible.
- Prefer evidence from tests, inspection, or reproducible checks over confidence.
- If validation is impossible, record why and what would validate the change later.

## Commit Discipline

- Keep each change set focused and easy to review.
- Do not bundle unrelated fixes.
- Do not commit `.env`, `logs/`, `state/`, `.venv/`, or other generated artifacts.
- If a change affects runtime behavior, update `README.md` in the same change set unless the change is strictly internal infrastructure.
- Prefer committing soon after a completed change set rather than letting multiple tasks drift together.

## Anti-Patterns

- Starting implementation before reading the prior framework files.
- Treating assumptions as facts.
- Skipping validation because the change looks small.
- Reusing earlier outputs without re-checking them.
- Letting one unclear requirement expand into unrelated work.
- Finalizing a task without updating the task log when a reusable lesson was learned.
- Claiming completion before an explicit validation step has happened.
- Promoting one-off mistakes into durable lessons.
- Letting the framework go stale instead of updating it when it is incomplete.
