---
tags: [phase/5, population, elites]
updated: 2026-07-11
---

# Phase 5 — Population dynamics (scaffold)

## Goal

Move from **single active lineage** toward an operator-curated **elite archive** and explicit **parent selection** for mutations. UI/CLI remain the operator console — not the organism brain.

## Delivered (scaffold)

| Item | Status |
|------|--------|
| Elite registry `artifacts/elites/registry.json` | ☑ |
| `seo elite list \| promote \| demote \| select` | ☑ |
| Genomes UI: promote / demote + elite table | ☑ |
| Mutate parent picker (auto · active · elite · genome) | ☑ |
| `seo mutate --parent-id <id>` resolves path correctly | ☑ |
| Job runner passes `--parent-id` | ☑ |
| **Auto selection** `active \| fitness_rank \| tournament` | ☑ |
| Evolve re-selects parent before each mutation | ☑ |
| Auto-promote accepts to elites when select≠active | ☑ |
| **Multi-lineage budgets** (slots + caps + schedule) | ☑ |
| `seo evolve --lineages N` multi-lineage evolve | ☑ |

## Multi-lineage budgets

| Knob | Meaning |
|------|---------|
| `max_lineages` / `--lineages` | Concurrent lineage slots (1 = classic) |
| `max_eval_cycles_per_lineage` | Per-slot eval cap (0 = off) |
| `max_mutations_per_lineage` | Per-slot mutation cap (0 = off) |
| `max_episodes_total` | Global seed-episode ceiling |
| `lineage_schedule` | `round_robin` or `fitness_rank` pick next slot |

```powershell
seo evolve --dry-run --cycles 6 --lineages 3 --mut-per-lineage 1 \
  --cycles-per-lineage 3 --lineage-schedule round_robin --select fitness_rank
```

Module: `src/organism/lineages.py` · population path in `run_evolve_population`.

## Selection policies

| Policy | Behavior |
|--------|----------|
| `active` | Current active_genome pointer (single lineage) |
| `fitness_rank` | Highest last fitness among elites + active + recent DB |
| `tournament` | Sample k candidates, pick best fitness in shortlist |

```powershell
seo elite select --policy fitness_rank
seo mutate --dry-run --select fitness_rank
seo evolve --dry-run --cycles 3 --select tournament --tournament-k 3
```

## Not yet (later Phase 5)

- [ ] Multi-agent same-map Watch
- [ ] Solo vs population experiment write-up
- [ ] Hard resource isolation between lineages (Docker-per-lineage)

## Operator flow

```powershell
# Promote a strong genome
seo elite promote g_xxxxxxxx --note "holdout champ"

# Mutate from that elite (not only active)
seo mutate --dry-run --ablation Bc --parent-id g_xxxxxxxx

# Or: seo ui → Genomes (promote) → Run → Mutate → Parent genome
```

## Code map

| Path | Role |
|------|------|
| `src/organism/elites.py` | Registry promote/demote/list/resolve |
| `src/organism/selection.py` | fitness_rank / tournament parent pick |
| `src/organism/lineages.py` | slots, budgets, pick schedule |
| `src/organism/evolve.py` | select + auto_elite + population evolve |
| `src/organism/mutation.py` | `resolve_parent_genome(..., parent_id=)` |
| `src/organism/cli.py` | `seo elite *` · mutate/evolve `--select` |
| `src/organism/observer/app.py` | Genomes + Run parent / select UI |
| `src/organism/observer/jobs.py` | argv builders for select + parent |

## Design notes

- Elites are **references** to existing genome dirs (no duplicate brain).
- Promoting does **not** rewrite `active_genome.json`.
- Accept still promotes via the normal mutation accept path.
- Registry is the elite source of truth; SQLite status may be tagged `elite` when not `active`.

## See also

- [[Roadmap]]
- [[Phase 4 Observer UI]]
- [[Home]]
