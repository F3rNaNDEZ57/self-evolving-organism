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
# UI: Overview → Export lab note
```

Writes `self-evolving-organism-docs/Runs/YYYY-MM-DD-….md` and appends this index.

## Index

| Date | Note | Baseline | Result |
|------|------|----------|--------|
| 2026-07-11 | [[2026-07-11-live-ablation-weight-fix]] | B0/Bw/Bc/Bcw live free NIM | δ −10.5 → **−2.5** after weight fix; δ still fail |
| 2026-07-11 | [[2026-07-11-soft-critic-delta-success]] | soft critic + sequential Bcw | **δ = +4.44 · success=True** |
| 2026-07-11 | [[2026-07-11-evolve-evo-7881f184b0]] | evolve dry-run export demo | auto-export from last_evolve_report |

