---
tags: [phase/3, critic, nim, free-tier, router, metrics]
updated: 2026-07-11
---

# Phase 3 — Free NIM pool + critic

## Goal

Multi-model quality control on **free NIM only**: critic gate, summarizer context, role router, budgets, mutation memory, measurable waste reduction.

## Pipeline

```text
parent eval → mutation memory (SQL) → summarize → propose (coder)
  → critic (static/schema AST → NIM/dry) → apply → eval → ε
                 │ reject → skip Docker
```

| Role | Pin (default) |
|------|---------------|
| code | `deepseek-ai/deepseek-v4-flash` |
| critique | `nvidia/nemotron-3-nano-30b-a3b` |
| summarize | `meta/llama-3.1-8b-instruct` |

## Layers

| Layer | Role |
|-------|------|
| Mutation memory | Last K accepts/rejects from SQLite → prompts |
| Summarizer | Episode distill bullets/hints |
| Static + schema AST | Imports · `obs.ticks` · `random.choice(weights=)` |
| Dry / free NIM critic | JSON approve/reject + taxonomy |
| Metrics | accept rate · critic reject rate · tokens/gain |

## CLI

```powershell
seo mutate --ablation Bc
seo metrics
seo critic-ab --n 6
seo pins
seo ablate --live --max-mutations 3
```

## Live field results (2026-07-11)

See full write-up: [[Runs/2026-07-11-live-ablation-weight-fix]]

| Suite | Bw holdout | Bcw − B0 | Code accepts | Notes |
|-------|------------|----------|--------------|-------|
| `abl_01d836c6d5` (pre weight fix) | 0.49 | **−10.47** | 0/6 | weight thrash · Docker crashes |
| `abl_dd5cb56e83` (post fix) | **8.45** | **−2.51** | 0/6 | schema contract_break · no crashes |

Pool (all-time after suite B): critic reject rate **~61%** · evals avoided **11** · tokens ~177k · `contract_break` taxonomy live.

## Deliverables

- [x] Free multi-model pins
- [x] Critic + reject taxonomy + gate
- [x] Metrics (`seo metrics`)
- [x] Router + summarizer context
- [x] Offline critic A/B
- [x] Live free-NIM mutate / evolve / ablate field trial
- [x] Mutation memory (SQL lessons)
- [x] Schema contract AST (ticks / choice weights)
- [x] Soft-threshold `other`/`low_value` conf&lt;0.6 → soft_pass
- [x] Raise free-NIM code accepts (Bc 3/8) + **δ success** [[Runs/2026-07-11-soft-critic-delta-success]]

## See also

- [[Phase 2 Hardening]]
- [[Runs/2026-07-11-live-ablation-weight-fix]]
- [[NIM Pin Log]]
- [[Roadmap]]
