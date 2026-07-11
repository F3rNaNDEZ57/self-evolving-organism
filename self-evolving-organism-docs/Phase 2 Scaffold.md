---
title: Phase 2 Scaffold
tags:
  - phase/2
  - implementation
status: active
updated: 2026-07-11
---

# Phase 2 Scaffold

> [!success] Scaffold live
> Package installable; world/eval/CLI/Docker smoke green.
>
> Dashboard: [[System Map]] · Rules: [[Working Rules]]

---

## What exists

| Area | Location | Status |
|------|----------|--------|
| Package | `src/organism/` | ✅ |
| Seed genome | `genomes/seed/{policy,heuristics,memory_hooks}.py` | ✅ |
| Pre-reg config | `config/experiment_v0.prereg.yaml` | ✅ |
| NIM pins | `config/nim.pinned.yaml` + `.env` | ✅ |
| CLI | `seo` entry point | ✅ |
| Tests | `tests/test_world_eval.py` | ✅ 2 passed |
| Artifacts DB | `artifacts/seo.sqlite` | created on `seo init` |

---

## CLI commands

```powershell
.\.venv\Scripts\Activate.ps1
seo init
seo demo --seed 0
seo eval --ablation B0
seo eval --ablation Bw
seo pins
seo docker-smoke
seo mutate-propose   # NIM proposal only (not applied yet)
```

### Smoke results (scaffold day)

| Check | Result |
|-------|--------|
| pytest | 2 passed |
| demo B0 seed 0 | score ~12.5, food 4 |
| eval B0 (8 train seeds) | fitness ~16.85 |
| eval Bw | fitness ~-0.18 (untrained weights, expected weak) |
| pins | key set, free model ids |
| docker-smoke | network_blocked + smoke_pass |

---

## Mutation loop (implemented)

```powershell
seo mutate --dry-run --ablation Bc   # offline deterministic patch
seo mutate --ablation Bc             # free NIM propose → apply → validate → eval → accept/reject
seo mutate --ablation Bcw            # code mutation + weight training ablation
```

Pipeline:

1. Eval parent on train seeds  
2. NIM JSON proposal (`files` + `rationale`) — or dry-run greedier policy  
3. Copy parent → `artifacts/genomes/{id}/`, overwrite whitelist files  
4. Static validate (AST, forbidden imports/calls, Policy interface)  
5. Eval candidate  
6. **Accept** if `fitness_c ≥ fitness_p + ε` → promote `active_genome.json` + archive parent  
7. Persist `mutations` row + `artifacts/mutations/{id}.json`

### Smoke (2026-07-11)

| Run | decision | parent → candidate | model |
|-----|----------|-------------------|--------|
| `seo mutate --dry-run` | **accepted** | 16.85 → 18.42 | dry_run |
| `seo mutate --ablation Bc` | **accepted** | 18.42 → **31.85** | `deepseek-ai/deepseek-v4-flash` |

Active genome pointer: `artifacts/active_genome.json`

## Ablation suite (implemented)

```powershell
seo ablate --quick                 # 3 train + 3 holdout seeds, 1 dry-run mut
seo ablate --dry-run               # full pre-reg seeds, dry-run muts
seo ablate --live --max-mutations 3
seo ablate --arms B0,Bcw --quick   # subset
```

| Arm | Meaning |
|-----|---------|
| **B0** | Fixed seed, no weights |
| **Bw** | Train numpy weights on train seeds → checkpoint → holdout |
| **Bc** | Up to N code mutations (dry-run or NIM), no weights |
| **Bcw** | Code mutations + weight train on final genome |

**Success claim:** holdout `Bcw ≥ B0 + δ` (δ default **0.30**).  
Report JSON: `artifacts/last_ablation_report.json` and `artifacts/ablations/{run_id}.json`.

### Quick smoke (2026-07-11)

| arm | holdout fit | mut |
|-----|-------------|-----|
| B0 | ~9.0 | 0 |
| Bw | ~-1.9 | 0 |
| Bc | ~9.0 | 0/1 (dry-run not accepted on short seed set) |
| Bcw | ~-1.9 | 0/1 |
| **δ** | Bcw−B0 ≈ **-10.9** · success=**False** (valid negative / under-budget result) |

## Weight checkpoints (implemented)

```powershell
seo weights train --passes 1          # train + save under artifacts/weights/
seo weights list
seo weights show latest               # or best / w_<id>
seo eval --ablation Bw --weights latest
```

Layout:

```text
artifacts/weights/
  w_<id>.npz              # theta + baseline + feature_dim
  w_<id>.json              # sidecar meta (sha256, genome_id, fitness…)
  latest.json              # pointer
  best.json                # best train_fitness pointer
  index.jsonl              # append-only log
```

Also registered in SQLite `weight_checkpoints`. Ablation suite Bw/Bcw uses the same API.

### Smoke (2026-07-11)

| Command | Result |
|---------|--------|
| `seo weights train --passes 1` | checkpoint `w_*` · feature_dim 27 · 8 episodes |
| `seo weights list` | 1 row + DB |
| `seo eval --weights latest` | loads checkpoint and runs |

## Evolve loop — schedule + plateau (implemented)

```powershell
seo evolve --cycles 5 --dry-run --every 8 --plateau 20 --max-mutations 5
seo evolve --cycles 10 --live --ablation Bc
```

| Trigger | Meaning |
|---------|---------|
| **schedule** | After `mutate_every_episodes` seed-episodes since last mutation |
| **plateau** | Last `plateau_episodes` fitness samples flat (span ≤ `plateau_epsilon`) or no beat of prior best |

Config: `config/experiment_v0.prereg.yaml` → `evolve:` and `genomic:`.  
Report: `artifacts/last_evolve_report.json` · `artifacts/evolve/{run_id}.json`

### Smoke (2026-07-11)

| Field | Value |
|-------|--------|
| command | `seo evolve --cycles 3 --dry-run --every 8 --max-mutations 2` |
| episodes | 24 |
| triggers | `mutate_schedule` ×2 |
| mutations | 0 accepted / 2 rejected (already-strong active genome) |
| pytest | **11 passed** |

## Not yet implemented (next slices)

- [x] Full ablation runner B0/Bw/Bc/Bcw + holdout δ  
- [x] Weight checkpoints under `artifacts/weights/`  
- [x] Schedule/plateau auto mutation triggers (`seo evolve`)  
- [ ] Docker-isolated episode eval (today: host eval after AST jail)  
- [ ] Runs/ vault note auto-export (optional)

---

## Layout reminder

```text
src/organism/     kernel + runtime (frozen harness)
genomes/seed/     whitelist mutable modules
config/           experiment + nim pins
artifacts/        sqlite, genomes, proposals (gitignored)
```

---

## See also

[[Roadmap]] · [[Phase 1 Research Package]] · [[NIM Pin Log]] · [[Open Decisions]] · [[Home]]
