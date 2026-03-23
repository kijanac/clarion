# Execution Plans

Owner: TBD
Status: Active
Last Updated: 2026-03-22

## Purpose

Execution plans are first-class artifacts, not throwaway docs.
Check them in. Update them as work progresses. Log decisions.

## How Exec Plans Relate to Other Artifacts

```
spec (what to build)
  → agent plan (how to build it — session scratchpad)
    → exec plan (checked-in progress log with decisions)
      → ADR (permanent record of key decisions made during execution)
```

| Artifact | When written | Audience | Lifespan | Lives in |
|---|---|---|---|---|
| **Spec** | Before work starts | Humans defining requirements | Until implemented | issues, docs, PRs |
| **Agent plan** | During a session | Agent's own working memory | Session-scoped, ephemeral | `.claude/plans/` |
| **Exec plan** | During implementation | Anyone picking up the work | Until completed, then archived | `docs/exec-plans/` |
| **ADR** | After a decision is made | Future humans/agents asking "why?" | Permanent | `docs/decisions/` |

**When to promote an agent plan to an exec plan:** When the work is
non-trivial — multi-session, involves architectural choices, or someone
else may need to pick it up. If the agent plan contains decisions worth
preserving, promote it here.

**When to extract an ADR from an exec plan:** When the decision log
contains a choice that constrains future work. Move the decision to
`docs/decisions/NNN-title.md` and link back from the exec plan.

**Anti-pattern:** Gitignoring plans. If a plan is worth writing, it's
worth checking in. Discarded plans are invisible context that future
agents and humans can't learn from.

## Current Plans

<!-- Add plans as numbered files: 001-feature-name.md -->

| # | Plan | Status |
|---|------|--------|
| — | (none yet) | — |

## Plan Template

Use `docs/exec-plans/NNN-title.md` with this structure:

```markdown
# NNN: Title

Status: In Progress | Complete | Abandoned
Started: 2026-03-22
Completed: 2026-03-22

## Goal
One sentence.

## Steps
- [ ] Step 1
- [ ] Step 2

## Decision Log
| Date | Decision | Rationale |
|------|----------|-----------|
```
