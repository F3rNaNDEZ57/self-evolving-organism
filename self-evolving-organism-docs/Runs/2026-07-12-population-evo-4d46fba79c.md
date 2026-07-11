---
title: Population evolve evo_4d46fba79c
tags:
  - run
  - phase/5
  - population
run_id: evo_4d46fba79c
status: complete
updated: 2026-07-12
source: C:/Projects/self-evolving-organism/artifacts/last_evolve_report.json
---

# Population evolve evo_4d46fba79c

## Summary

| Field | Value |
|-------|-------|
| run_id | `evo_4d46fba79c` |
| ablation | Bc |
| dry_run | False |
| episodes_run | 32 |
| mutations | acc=0 / rej=1 / fail=0 / att=1 |
| start_genome | `g_0a2b03eafe` |
| final_genome | `g_0a2b03eafe` |
| fitness first → last | 28.1316 → 28.1316 |
| fitness best | 28.1316 |
| max_lineages | 3 |
| lineage_schedule | round_robin |

## Fitness history

```
28.132, 28.132, 28.132, 28.132
```

## Lineage slots

| slot | genome | fitness | evals | mut att | exhausted |
|------|--------|---------|-------|---------|-----------|
| 0 | `g_0a2b03eafe` | 28.1316 | 2 | 1 | False |
| 1 | `g_0a0a9d34d2` | 28.1316 | 1 | 0 | False |
| 2 | `g_9397e9c8c8` | 28.1316 | 1 | 0 | False |

## Selection events

- `g_0a2b03eafe` — slot=0 hold_lineage (multi-lineage preserves slot parent)

## Mutation triggers

mutate_schedule

## Operator notes

Short validation after **proposal-quality** gate (`feat/proposal-quality`).

- 1 mutation attempted (4 cycles / schedule) — reached **fitness eval** (not empty/nonsense)
- Rejected fairly: candidate **21.74** < parent **28.13**+ε
- Quality gate did not fire as fail here — NIM produced a usable patch that simply lost selection

## Source

- Report: `C:\Projects\self-evolving-organism\artifacts\last_evolve_report.json`
- Exported: 2026-07-12 01:09:51

→ [[Runs/README|Runs index]] · [[Phase 5 Population]] · [[System Map]]
