---
title: Working Rules
tags:
  - meta
  - process
  - dashboard
aliases:
  - Vault rules
  - After every task
  - Agent rules
status: active
updated: 2026-07-11
---

# Working Rules

> [!warning] Standing process rule
> **After every completed task**, update this vault **and** the dashboard canvas.
>
> Machine-facing copy: repo-root `AGENTS.md`

---

## Rule 1 — Vault + canvas after every task

When a task finishes (research, code, config, experiment, decision):

| Step | Action |
|------|--------|
| 1 | Update relevant notes (status, checklists, new findings) |
| 2 | Update **[[System Map]]** (phase, next action, verified infra) |
| 3 | Ensure **[[Home]]** still points at current reality |
| 4 | Never store API keys here — only in `.env` |

### Done means

- [ ] Task deliverable itself complete  
- [ ] Vault truthful  
- [ ] Canvas dashboard truthful  
- [ ] No secrets in git/vault  

### Tiny tasks

If project **state** changed → still update vault/canvas.  
If pure no-op polish → canvas optional.

---

## Rule 2 — Canvas is the dashboard

**[[System Map]]** is the project dashboard, not a one-off diagram.

Keep current:

- Phase 0 / 1 / 2… status  
- **Next action** block  
- Live pins / Docker / freezes  
- Clean layout (readable, no overlaps)  

---

## Rule 3 — Honor the freeze

See [[Open Decisions]]. Do not reopen D1–D12 without an explicit owner decision and amendment log entry.

---

## Rule 4 — Free NIM + Docker

- Default models: free NIM only → [[NIM Pin Log]]  
- Organism runtime: Docker `--network none` (Phase 1 verified)  

---

## Rule 5 — GitNexus

- Repo is indexed — see [[GitNexus]]  
- After major code changes: `npx gitnexus analyze`  
- Prefer impact/query tools before large refactors (see `AGENTS.md` gitnexus block)  

---

## See also

[[Home]] · [[System Map]] · [[GitNexus]] · [[Open Decisions]] · [[Phase 1 Research Package]] · repo `AGENTS.md`
