# Lessons

Purpose: this file stores durable, reusable lessons that should improve future task execution across projects.
Keep the content short, specific, and evidence-based. Only promote lessons here when they are broadly applicable.
If a lesson does not generalize beyond one task, keep it in `TASK_LOG.md` instead.

## Durable Rules

### Do Not Assume Unstated Requirements

Problem pattern: a task is implemented using an inferred requirement that was never stated.
Preventive rule: treat missing requirements as unknowns and document the assumption before acting.
When it applies: ambiguous requests, partially specified behavior, or tasks with multiple plausible interpretations.
Confidence level: high.
Last updated: 2026-04-17.

### Validate Before Claiming Completion

Problem pattern: work is declared done without a check that the intended behavior actually holds.
Preventive rule: pair every implementation with at least one validation step that could fail.
When it applies: code changes, workflow changes, generated files, and any task with verifiable output.
Confidence level: high.
Last updated: 2026-04-17.

## Repeated Failure Patterns

### Reuse Requires Re-Validation

Problem pattern: prior outputs, snippets, or patterns are reused as if they were still correct.
Preventive rule: verify any reused artifact against current repo state or current requirements before relying on it.
When it applies: copied code, prior conclusions, cached assumptions, or previous task outputs.
Confidence level: high.
Last updated: 2026-04-17.

## Validation Heuristics

### Prefer Evidence Over Confidence

Problem pattern: a change feels correct but has no direct evidence behind it.
Preventive rule: use tests, inspection, comparison, or reproducible checks as the default standard for completion.
When it applies: implementation work, refactors, data changes, and documentation updates that affect behavior.
Confidence level: high.
Last updated: 2026-04-17.

## Communication Heuristics

### Separate Facts From Assumptions

Problem pattern: reports blur what is observed with what is inferred.
Preventive rule: label facts, assumptions, and open questions separately in plans and summaries.
When it applies: task updates, handoffs, risk notes, and final reports.
Confidence level: high.
Last updated: 2026-04-17.

## Implementation Heuristics

### Decompose When Complexity Rises

Problem pattern: one person or one pass tries to handle all facets of a complex task.
Preventive rule: split work into planner, implementer, reviewer, validator, and documentation roles when the task is non-trivial.
When it applies: multi-step changes, mixed research and implementation, or anything with a meaningful verification burden.
Confidence level: high.
Last updated: 2026-04-17.

### Preserve Persisted Runtime State On Restart

Problem pattern: initialization code reseeds default runtime data and silently overwrites persisted active state.
Preventive rule: when state is meant to survive restarts, initialization should insert missing defaults and then recover from persisted records instead of reseeding everything.
When it applies: SQLite-backed services, task queues, lifecycle trackers, pool allocators, and any restart-sensitive workflow.
Confidence level: high.
Last updated: 2026-04-21.

## Research Heuristics

### Prefer Primary Evidence

Problem pattern: conclusions are built from second-hand summaries or memory when primary evidence is available.
Preventive rule: consult the source artifact, repository file, test output, or official reference whenever possible.
When it applies: repo analysis, technical questions, source-of-truth decisions, and verification-sensitive tasks.
Confidence level: high.
Last updated: 2026-04-17.

### Prefer Exchange Metadata Over Text Parsing

Problem pattern: runtime-critical exchange facts are inferred from human-readable announcements even though the exchange exposes a machine-readable source of truth.
Preventive rule: use official exchange metadata or account history endpoints first for trading schedule, lifecycle, or realized PnL decisions; fall back to text parsing only when the API cannot provide the needed field.
When it applies: delist time, contract status, settlement state, execution history, and exchange-managed close events.
Confidence level: high.
Last updated: 2026-04-21.

## Task Triage Heuristics

### Match Process To Risk

Problem pattern: every task gets the same amount of ceremony regardless of scope or risk.
Preventive rule: use the lightest process that is safe, but raise the bar immediately when uncertainty, coupling, or impact increases.
When it applies: triage, planning, and deciding whether to invoke subagents.
Confidence level: medium.
Last updated: 2026-04-17.
