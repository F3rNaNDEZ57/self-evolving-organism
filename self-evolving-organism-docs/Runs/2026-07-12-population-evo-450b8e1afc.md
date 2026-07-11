---
title: Population evolve evo_450b8e1afc
tags:
  - run
  - phase/5
  - population
run_id: evo_450b8e1afc
status: complete
updated: 2026-07-12
source: C:/Projects/self-evolving-organism/artifacts/last_evolve_report.json
---

# Population evolve evo_450b8e1afc

Post-diversity-fix live multi-lineage (hold slot parent + content-hash fill).

```powershell
seo evolve --live --cycles 8 --lineages 3 --select fitness_rank --ablation Bc --max-mutations 6
```

## Summary

| Field | Value |
|-------|-------|
| run_id | `evo_450b8e1afc` |
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
| content diversity | **3 unique hashes** |

## Fitness history

```
28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.132, 28.132
```

## Lineage slots

| slot | genome | fitness | evals | mut att | exhausted |
|------|--------|---------|-------|---------|-----------|
| 0 | `g_0a2b03eafe` | 28.1316 | 3 | 1 | False |
| 1 | `g_9397e9c8c8` | 28.1316 | 3 | 1 | False |
| 2 | `g_1203f8e874` | 28.1316 | 2 | 1 | False |

## Selection events

- `g_0a2b03eafe` — slot=0 hold_lineage (multi-lineage preserves slot parent)
- `g_9397e9c8c8` — slot=1 hold_lineage (multi-lineage preserves slot parent)
- `g_1203f8e874` — slot=2 hold_lineage (multi-lineage preserves slot parent)

## Mutation triggers

mutate_schedule, mutate_schedule, mutate_schedule

## Operator notes

**Diversity fix worked:** all three selects are `hold_lineage` with distinct genome ids and content keys (not champion collapse).

| Slot | Parent | Reject reason |
|------|--------|----------------|
| 0 | `g_0a2b03eafe` | fitness == parent (need +ε) |
| 1 | `g_9397e9c8c8` | critic **low_value** food-direction again |
| 2 | `g_1203f8e874` | critic **contract_break** (broken policy.py proposal) |

**Follow-up code:** parent `validate_genome_dir` on open; static reject of food-only re-tweaks when lessons flag them; stronger propose constraints.

## Source

- Report: `C:\Projects\self-evolving-organism\artifacts\last_evolve_report.json`
- Exported: 2026-07-12

→ [[Runs/README|Runs index]] · [[Phase 5 Population]] · [[System Map]]
