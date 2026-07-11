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

## Multi-agent same-map Watch (viz only)

| Item | Status |
|------|--------|
| Shared food arena (host-only) | ☑ `organism/multiagent.py` |
| UI Watch mode **multi** (2–6 agents) | ☑ live stream + GIF |
| CLI `seo watch --multi N` / `--agents a,b` | ☑ |

**Not for fitness claims** — policies compete on one map for operator eyes only.

```powershell
seo watch --multi 3 --seed 0 --gif artifacts/replays/last_watch_multi.gif
seo watch --agents g_xxx,g_yyy --gif artifacts/replays/duel.gif
# UI: seo ui → Watch → Mode multi → pick agents → Live stream
```

## Live mutate reliability

| Item | Status |
|------|--------|
| Truncated NIM JSON recovery + parse retry | ☑ `fix/mutation-proposal-parse` |
| Fitness **rejected** = exit 0 (science OK) | ☑ |
| Fitness **failed** parse = exit 1 | ☑ |

Rejected patches (e.g. rest-more heuristics losing to parent ~28) are normal under free NIM.

## Bw holdout tool

```powershell
seo weights train --passes 4
seo weights holdout --weights latest          # B0 vs Bw on holdout seeds
seo weights holdout --passes 4                # train then compare
seo weights diagnose --weights latest         # recommendation
seo weights train --passes 4 --keep-if-beats-b0
seo weights train --on-seed --passes 4        # experiment: seed genome only
seo weights holdout --on-seed --passes 2
seo runs export --kind weights_holdout
# UI: Run → Weights → seed checkboxes · Start B0 vs Bw holdout
```

Writes `artifacts/last_weights_holdout.json` / `last_weights_diagnose.json`.

**Safety:** if diagnose says do not prefer weights, mutate/evolve **Bcw → Bc** unless `--force-bcw`.

## Dual-timescale best-of phenotype

For **Bw/Bcw** evals with a frozen checkpoint, `evaluate_genome` runs **code-only** and **with-weights**, keeps the better fitness (`phenotype=code_only|with_weights`). Weak scorers cannot tank strong heuristics.

## Runs export (lab notes)

| Item | Status |
|------|--------|
| `seo runs export` from last evolve/ablate/mutation | ☑ |
| Population evolve notes include lineage slots | ☑ |
| UI Overview → Export lab note | ☑ |
| Updates [[Runs/README]] index | ☑ |

```powershell
seo evolve --dry-run --lineages 3 --cycles 4
seo runs export --kind evolve
```

## Multi-lineage diversity (2026-07-12)

| Behavior | Detail |
|----------|--------|
| Slot fill | Content-hash unique parents (clones of same code collapse) |
| Seed arm | `g_seed` included as exploration parent when underfilled |
| Mutate parent | Multi-lineage **holds slot genome** (no global fitness_rank overwrite) |
| Lessons | Coder prompt steers off repeated `low_value` food-direction tweaks |

```powershell
seo evolve --live --cycles 8 --lineages 3 --select fitness_rank --ablation Bc --max-mutations 6
# --select applies only on single-lineage; multi-lineage preserves per-slot parents
```

## Not yet (later Phase 5)

- [ ] Hard resource isolation between lineages (Docker-per-lineage)
- [ ] Multi-agent used in fitness / selection (if ever)

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
| `src/organism/multiagent.py` | same-map multi-agent Watch arena (viz only) |
| `src/organism/runs_export.py` | last_* report → Runs/ markdown |
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
