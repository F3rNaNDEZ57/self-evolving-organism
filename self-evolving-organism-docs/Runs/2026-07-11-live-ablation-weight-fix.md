---
tags: [run, ablation, phase/2, phase/3, free-nim]
updated: 2026-07-11
---

# Live ablations — weight fix comparison

## Setup

- Free NIM only · Docker isolation · prereg seeds train `[0–7]` holdout `[100–107]`
- `max_mutations=3` · `train_passes` 2→4 after fix · δ success = **0.30**
- No API keys in this note

## Suite A — before weight fix · `abl_01d836c6d5`

| Arm | Holdout | Mut acc/att |
|-----|---------|-------------|
| B0 | **10.95** | 0/0 |
| Bw | **0.49** | 0/0 |
| Bc | 10.95 | 0/3 |
| Bcw | **0.49** | 0/3 |

- **δ (Bcw − B0) = −10.47** · success=**False**
- Code accepts: 0 · Weight pathway catastrophic (random thrash vs heuristics)
- Failures: `Observation.ticks`, `random.choice(weights=)`, bad `Policy.__init__`, unparsable JSON

## Suite B — after weight fix · `abl_dd5cb56e83`

Fixes shipped: BC bootstrap · engineered features · return-to-go · keep-best · `explore_eval=0` · schema AST · mutation memory.

| Arm | Train | **Holdout** | Mut acc/att |
|-----|-------|-------------|-------------|
| B0 | 16.85 | **10.95** | 0/0 |
| Bw | 5.26 | **8.45** | 0/0 |
| Bc | 16.85 | **10.95** | **0/3** |
| Bcw | 5.26 | **8.45** | **0/3** |

- **δ (Bcw − B0) = −2.51** · success=**False**
- Attribution: `gain_from_code=0` · `gain_from_weights=−2.51` · code-only holdout = B0
- **0 Docker crashes** this suite
- Critic: 5/6 rejects (incl. **contract_break** on `choice(weights=)`) · 1 fitness flatline
- Mutation memory events: 6 · suite ~48k tokens

### Before → after

| Metric | Suite A | Suite B |
|--------|---------|---------|
| Bw holdout | 0.49 | **8.45** |
| Bcw − B0 | −10.47 | **−2.51** |
| Schema crashes | yes | **none** |

## Active-genome weight smoke (same day)

- Genome: `g_04081bbdc6` (evolved) · ckpt `w_ce6519e7f716`
- Train fitness after p4: **32.88**
- Holdout **B0 = Bw = 22.11** (weights clone heuristic; no collapse)

## Artifacts (repo `artifacts/`, gitignored)

- `last_ablation_report.json` → suite B
- `ablations/abl_01d836c6d5*` · `abl_dd5cb56e83*`
- `last_pool_metrics.json`
- `weights/w_ce6519e7f716.npz`

## Interpretation

1. Weight fix **worked** (Δ −10.5 → −2.5 on suite seed).
2. Free-NIM **code accepts still 0/6** under max_mutations=3 — δ claim blocked by code path + residual weight gap.
3. Critic + schema gates **reduce crash waste**; soft `other` rejects still dominate.

## Next

- Soft-threshold critic `other` conf&lt;0.6 or more evolve cycles for accepts
- Optional: Bcw mutation parent eval without train-mode noise
- Phase 4 UI when science loop is “good enough”

## See also

- [[Phase 2 Hardening]]
- [[Phase 3 Critic]]
- [[Home]]
