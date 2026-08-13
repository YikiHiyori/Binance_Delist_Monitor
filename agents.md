# Agents Framework

Purpose: this repository uses a lightweight execution system so future tasks can be decomposed, delegated, validated, and reflected on without relying on hidden memory.
Future runs should skim this file at task start before doing anything substantial.

## When To Invoke Subagents

- Use subagents when the task is non-trivial, spans multiple concerns, or benefits from parallel work.
- Use subagents when research, implementation, review, validation, and documentation can be separated.
- Use subagents when uncertainty is material and needs independent confirmation.
- Do not use subagents for simple one-step edits unless the task grows during execution.

## Standard Subagent Roster

| Agent | Responsibility | Output |
| --- | --- | --- |
| Planner Agent | Restates the task, identifies scope, assumptions, risks, and dependencies, and proposes a stepwise path. | Task plan with checkpoints and handoff criteria. |
| Research Agent | Collects facts, source details, examples, or repo context without changing files. | Evidence summary with citations or file references. |
| Implementer Agent | Makes the requested file or code changes within a clearly assigned scope. | Concrete edits and a short change summary. |
| Reviewer Agent | Checks correctness, consistency, regressions, and missing cases. | Findings, severity, and recommended fixes. |
| Validator Agent | Runs tests, smoke checks, or manual verification and reports evidence. | Validation results and any failures. |
| Documentation Agent | Updates README, workflow docs, templates, or notes when the task changes how future work should be done. | Clean documentation patches and brief rationale. |

## Delegation Rules

- Assign each subagent a bounded responsibility and a clear stopping point.
- Do not duplicate the same work in multiple subagents.
- Give each subagent the minimum context needed to do its job well.
- Prefer parallel work only when the write scope or question scope does not overlap.
- Do not let a subagent silently expand its scope without telling the orchestrator.
- If a subagent finds a conflict, it should report it instead of resolving it by guesswork.

## Handoff Contract

- Every handoff must include the goal, current state, known constraints, assumptions, and the next artifact needed.
- Every returned result must include what was changed or observed, what remains uncertain, and what should happen next.
- A handoff is incomplete if it omits validation evidence for a completed implementation step.
- The next agent should be able to continue without reconstructing the whole task from scratch.

## Escalation Rules

- Escalate when requirements conflict, the task boundary is unclear, or the safest path is not obvious.
- Escalate when a change could create broad side effects, data loss, or irreversible behavior.
- Escalate when evidence is insufficient and the decision matters.
- Escalate when a subagent output disagrees with repo state or prior lessons.
- Record the ambiguity rather than inventing certainty.

## Definition Of Done

- The requested work is implemented or the question is answered.
- Relevant validation has been performed and recorded.
- Uncertainty has been documented where it remains.
- The task log has been updated for durable or noteworthy outcomes.
- Durable lessons have been promoted to `LESSONS.md` when appropriate.

## Pre-Flight Checklist

- Read `agents.md`.
- Read `WORKFLOW.md`.
- Read `LESSONS.md`.
- Read the most recent relevant entries in `TASK_LOG.md`.
- Identify whether the task is trivial, normal, complex, or high-risk.
- Choose the smallest useful set of subagents.
- Write down assumptions, risks, dependencies, and validation steps before editing anything non-trivial.

## Post-Task Reflection Protocol

- Record what went well.
- Record what went wrong.
- Record what assumptions were false.
- Record what should be standardized.
- Record what rule would prevent the same mistake from recurring.
- Promote only durable, reusable lessons to `LESSONS.md`.
- Keep one-off observations in `TASK_LOG.md` instead of overfitting the durable memory.

## Enforcement Rules

- Never begin complex execution before reading the framework files.
- Never claim a task is complete without an explicit validation step.
- Never promote a lesson into durable memory unless it is reusable beyond a single task.
- Never trust previous outputs, snapshots, or intermediate artifacts blindly when they affect correctness.
- If the same kind of mistake appears twice, convert it into a durable rule in `LESSONS.md`.
- Prefer lightweight structured notes over long narrative text.
- Keep the framework alive by updating it when it becomes stale or incomplete.
