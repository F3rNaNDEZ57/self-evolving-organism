---
title: Population evolve evo_6a1f0edb0a
tags:
  - run
  - phase/5
  - population
run_id: evo_6a1f0edb0a
status: complete
updated: 2026-07-12
source: C:/Projects/self-evolving-organism/artifacts/last_evolve_report.json
---

# Population evolve evo_6a1f0edb0a

Live multi-lineage after food-repeat static gate (~10 min wall).

```powershell
seo evolve --live --cycles 8 --lineages 3 --select fitness_rank --ablation Bc --max-mutations 6
```

## Summary

| Field | Value |
|-------|-------|
| run_id | `evo_6a1f0edb0a` |
| ablation | Bc |
| dry_run | **False** (LIVE) |
| episodes_run | 64 |
| mutations | **acc=0 / rej=3 / fail=0 / att=3** |
| start_genome | `g_0a2b03eafe` |
| final_genome | `g_0a2b03eafe` |
| fitness first → last | 28.1316 → 28.1316 |
| fitness best | 28.1316 |
| max_lineages | 3 |
| lineage_schedule | round_robin |
| content diversity | **3 unique keys** · hold_lineage |

## Fitness history

```
28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.132
```

## Lineage slots

| slot | genome | fitness | evals | mut att | exhausted |
|------|--------|---------|-------|---------|-----------|
| 0 | `g_0a2b03eafe` | 28.1316 | 3 | 1 | False |
| 1 | `g_0a0a9d34d2` | 28.1316 | 3 | 1 | False |
| 2 | `g_9397e9c8c8` | 28.1316 | 2 | 1 | False |

## Selection events

- `g_0a2b03eafe` — slot=0 hold_lineage (multi-lineage preserves slot parent)
- `g_0a0a9d34d2` — slot=1 hold_lineage (multi-lineage preserves slot parent)
- `g_9397e9c8c8` — slot=2 hold_lineage (multi-lineage preserves slot parent)

## Mutation triggers

mutate_schedule, mutate_schedule, mutate_schedule

## Operator notes

Diversity + food-gate still healthy. Rejects:

| Slot | Parent | Reason |
|------|--------|--------|
| 0 | `g_0a2b03eafe` | **fitness** 26.98 &lt; 28.13+ε |
| 1 | `g_0a0a9d34d2` | **fitness** 24.01 &lt; 28.13+ε |
| 2 | `g_9397e9c8c8` | critic **nonsense** (empty proposal) |

2/3 reached real fitness eval (food-repeat spam reduced). Plateau under free NIM continues; not a harness failure.

## Source

- Report: `C:\Projects\self-evolving-organism\artifacts\last_evolve_report.json`
- Exported: 2026-07-12

→ [[Runs/README|Runs index]] · [[Phase 5 Population]] · [[System Map]]
