---
title: Population evolve evo_e7bd5a260f
tags:
  - run
  - phase/5
  - population
run_id: evo_e7bd5a260f
status: complete
updated: 2026-07-12
source: C:/Projects/self-evolving-organism/artifacts/last_evolve_report.json
---

# Population evolve evo_e7bd5a260f

**First multi-lineage live ACCEPT** under proposal-quality + diversity rails (~14 min).

```powershell
seo evolve --live --cycles 12 --lineages 3 --select fitness_rank --ablation Bc --max-mutations 9
```

## Summary

| Field | Value |
|-------|-------|
| run_id | `evo_e7bd5a260f` |
| ablation | Bc |
| dry_run | **False** (LIVE) |
| episodes_run | 96 |
| mutations | **acc=1 / rej=5 / fail=0 / att=6** |
| start_genome | `g_0a2b03eafe` |
| final_genome | **`g_c07765783a`** |
| fitness first → last | 28.1316 → 28.1316 (last slot eval) |
| fitness best | **28.7563** |
| max_lineages | 3 |
| lineage_schedule | round_robin |

## Fitness history

```
28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.756, 28.132, 28.132, 28.756, 28.132
```

## Lineage slots

| slot | genome | fitness | evals | mut att | exhausted |
|------|--------|---------|-------|---------|-----------|
| 0 | `g_0a2b03eafe` | 28.1316 | 4 | 2 | False |
| 1 | `g_c07765783a` | 28.7563 | 4 | 2 | False |
| 2 | `g_9397e9c8c8` | 28.1316 | 4 | 2 | False |

## Selection events

- `g_0a2b03eafe` — slot=0 hold_lineage (multi-lineage preserves slot parent)
- `g_0a0a9d34d2` — slot=1 hold_lineage (multi-lineage preserves slot parent)
- `g_9397e9c8c8` — slot=2 hold_lineage (multi-lineage preserves slot parent)
- `g_0a2b03eafe` — slot=0 hold_lineage (multi-lineage preserves slot parent)
- `g_c07765783a` — slot=1 hold_lineage (multi-lineage preserves slot parent)
- `g_9397e9c8c8` — slot=2 hold_lineage (multi-lineage preserves slot parent)

## Mutation triggers

mutate_schedule, mutate_schedule, mutate_schedule, mutate_schedule, mutate_schedule, mutate_schedule

## Operator notes

| Mut | Slot | Outcome |
|-----|------|---------|
| 1 | 0 `g_0a2b03eafe` | fitness reject 21.7 |
| 2 | 1 `g_0a0a9d34d2` | **ACCEPTED** → `g_c07765783a` @ **28.76** |
| 3 | 2 `g_9397e9c8c8` | fitness ~28.16 (&lt; +ε) |
| 4 | 0 | critic unsafe_import (`position`) |
| 5 | 1 (new parent) | fitness 24.8 &lt; 28.76 |
| 6 | 2 | fitness reject |

Science: free NIM **beat** the long plateau champion on a secondary lineage. Report `final_genome` = best slot (`g_c07765783a`). Multi-lineage may not auto-write `active_genome.json` — promote/pointer if operator wants this as global active.

## Source

- Report: `C:\Projects\self-evolving-organism\artifacts\last_evolve_report.json`
- Exported: 2026-07-12

→ [[Runs/README|Runs index]] · [[Phase 5 Population]] · [[System Map]]
