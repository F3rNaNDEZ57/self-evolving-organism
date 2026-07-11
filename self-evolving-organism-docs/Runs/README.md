---
title: Runs
tags:
  - run
  - lab
aliases:
  - Experiment runs
status: active
updated: 2026-07-11
---

# Runs

> [!info] Lab notebook folder
> Experiment write-ups live here after Phase 2 starts. Pattern: [[Artifact Management]].
>
> Canvas: [[System Map]] · Freeze: [[Open Decisions]]

## Template

Copy into `YYYY-MM-DD-short-name.md`:

```yaml
---
title: Run …
tags:
  - run
  - phase/2
run_id:
baseline: B0 | Bw | Bc | Bcw
genome_id:
parent_genome_id:
fitness:
holdout_fitness:
nim_model:
artifact_path:
weights_path:
status: planned | running | complete
---
```

## Auto-export (machine → vault)

After `seo evolve` / `ablate` / `mutate`, dump a lab stub from the last report:

```powershell
seo runs export --kind auto          # newest last_* report
seo runs export --kind evolve
seo runs export --kind ablate
seo runs export --kind mutation
seo runs export --kind weights_holdout
seo runs export --kind diagnose
seo runs export --kind soak
# UI: Overview → Export lab note
```

Writes `self-evolving-organism-docs/Runs/YYYY-MM-DD-….md` and appends this index.

## Index

| Date | Note | Baseline | Result |
|------|------|----------|--------|
| 2026-07-11 | [[2026-07-11-live-ablation-weight-fix]] | B0/Bw/Bc/Bcw live free NIM | δ −10.5 → **−2.5** after weight fix; δ still fail |
| 2026-07-11 | [[2026-07-11-soft-critic-delta-success]] | soft critic + sequential Bcw | **δ = +4.44 · success=True** |
| 2026-07-11 | [[2026-07-11-evolve-evo-7881f184b0]] | evolve dry-run export demo | auto-export from last_evolve_report |
| 2026-07-11 | [[2026-07-11-bw-holdout-wh-1783787663]] | weights_holdout | auto-export: 2026-07-11-bw-holdout-wh-1783787663 |
| 2026-07-11 | [[2026-07-11-bw-holdout-wh-1783789773]] | seed holdout | Bw−B0=**−2.51** · discarded |
| 2026-07-11 | [[2026-07-11-mutate-m-9b1d76cd30]] | mutation Bc (safety) | rejected 22.19 < 28.13 |
| 2026-07-11 | [[2026-07-11-seed-vs-active-weights-ab]] | seed vs active A/B | both Bw lag; prefer **Bc** |
| 2026-07-11 | [[2026-07-11-weights-diagnose-wd-1783790309]] | diagnose | auto-export: 2026-07-11-weights-diagnose-wd-178379030 |
| 2026-07-11 | [[2026-07-11-soak-soak-1783789768]] | soak | auto-export: 2026-07-11-soak-soak-1783789768 |
| 2026-07-11 | [[2026-07-11-weights-diagnose-wd-1783790481]] | diagnose | auto-export: 2026-07-11-weights-diagnose-wd-178379048 |
| 2026-07-11 | [[2026-07-11-soak-soak-1783790476]] | soak | auto-export: 2026-07-11-soak-soak-1783790476 |
| 2026-07-11 | [[2026-07-11-bw-holdout-wh-1783790480]] | weights_holdout | auto-export: 2026-07-11-bw-holdout-wh-1783790480 |
| 2026-07-11 | [[2026-07-11-mutate-m-d054d3532d]] | mutation | auto-export: 2026-07-11-mutate-m-d054d3532d |
| 2026-07-11 | [[2026-07-11-evolve-evo-f993560c5d]] | evolve | auto-export: 2026-07-11-evolve-evo-f993560c5d |
| 2026-07-11 | [[2026-07-11-bw-holdout-wh-1783790587]] | weights_holdout | auto-export: 2026-07-11-bw-holdout-wh-1783790587 |
| 2026-07-11 | [[2026-07-11-population-evo-308b7ef211]] | population | auto-export: 2026-07-11-population-evo-308b7ef211 |
| 2026-07-11 | [[2026-07-11-soak-soak-1783791309]] | live soak r=10 Bc | **acc=0/att=10** · fit 28.13 · genome stable |
| 2026-07-12 | [[2026-07-12-population-evo-f3f53426e0]] | multi-lineage live 3-slot | **acc=0/rej=3 critic low_value** · plateau 28.13 |

