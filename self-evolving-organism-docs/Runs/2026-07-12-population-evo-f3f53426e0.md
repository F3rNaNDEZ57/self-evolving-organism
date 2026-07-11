---
title: Population evolve evo_f3f53426e0
tags:
  - run
  - phase/5
  - population
run_id: evo_f3f53426e0
status: complete
updated: 2026-07-12
source: C:/Projects/self-evolving-organism/artifacts/last_evolve_report.json
---

# Population evolve evo_f3f53426e0

Live multi-lineage under **Bc** + `fitness_rank` (first live 3-slot stress after plateau soak).

```powershell
seo evolve --live --cycles 8 --lineages 3 --select fitness_rank --ablation Bc --max-mutations 6
```

## Summary

| Field | Value |
|-------|-------|
| run_id | `evo_f3f53426e0` |
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

## Fitness history

```
28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.132
```

## Lineage slots

| slot | genome | fitness | evals | mut att | exhausted |
|------|--------|---------|-------|---------|-----------|
| 0 | `g_0a2b03eafe` | 28.1316 | 3 | 1 | False |
| 1 | `g_0a2b03eafe` | 28.1316 | 3 | 1 | False |
| 2 | `g_0a2b03eafe` | 28.1316 | 2 | 1 | False |

## Selection events

- `g_0a2b03eafe` — slot=0 fitness_rank: best_fitness=28.1316 source=active
- `g_0a2b03eafe` — slot=1 fitness_rank: best_fitness=28.1316 source=active
- `g_0a2b03eafe` — slot=2 fitness_rank: best_fitness=28.1316 source=active

## Mutation triggers

mutate_schedule, mutate_schedule, mutate_schedule

## Operator notes

- All 3 rejects were **critic `low_value`**, not fitness losses — mutation memory blocked repeated `nearest_food_direction` tweaks.
- Slots were clones of the same champion → `fitness_rank` always re-selected `g_0a2b03eafe`.
- Multi-lineage harness OK; diversity did not enter genomes. Next: seed slots from distinct parents / force different failure-mode patches.

## Source

- Report: `C:\Projects\self-evolving-organism\artifacts\last_evolve_report.json`
- Exported: 2026-07-12

→ [[Runs/README|Runs index]] · [[Phase 5 Population]] · [[System Map]]
