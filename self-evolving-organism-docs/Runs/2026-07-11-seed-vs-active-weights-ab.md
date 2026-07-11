---
title: Seed vs active weights A/B
tags:
  - run
  - weights
  - phase/6
  - ab
run_id: seed-active-ab-2026-07-11
status: complete
updated: 2026-07-11
---

# Seed vs active weights A/B

Cross-suite comparison after Phase 6 rails (doctor · soak · package · safety Bc · `--on-seed`).

## Operator confirmation (this session)

| Step | Result |
|------|--------|
| `seo doctor` | OK · all checks green · active `g_0a2b03eafe` |
| `seo soak --rounds 3` | ok · doctor_ok · **acc=0/att=3** dry (expected) · fitness ~28.13 |
| `seo package` | `artifacts/packages/pkg_1783789769/` |
| `seo weights train --on-seed --passes 4` | `w_16f44b14ab36` · **discarded** (keep-if-beats-b0) |
| `seo weights holdout --on-seed --passes 2` | **Bw−B0 = −2.51** · beats_b0=False |
| `seo weights diagnose --weights latest` | **recommend_use_weights=False** · holdout Δ=−6.23 |
| `seo mutate` | **ablation=Bc** (safety rail) · **rejected** 22.19 < parent 28.13 |

## A/B table (holdout)

| Genome | Kind | B0 holdout | Bw holdout | Bw − B0 | Prefer weights? |
|--------|------|------------|------------|---------|-----------------|
| `g_0a2b03eafe` | **active** lineage | 15.39 | 9.16 | **−6.23** | **No** |
| `g_seed` | **seed** experiment | 10.95 | 8.45 | **−2.51** | **No** (discarded) |

Active also shows train gap B0 28.13 vs Bw 9.71 (Δ **−18.42**) — scorer is harmful even on train seeds under best-of phenotype framing (code path wins).

## Interpretation

1. **Code is the strong timescale.** Parent ~28; free-NIM candidates 0.2–22 still lose → selection working.
2. **Weights lag on both genomes.** Seed is *less bad* (−2.5 vs −6.2) but still negative after 2–4 train passes + keep-if-beats-b0.
3. **Safety rail confirmed live:** after diagnose negative, `seo mutate` logged `ablation=Bc` without `--force-bcw`.
4. **Do not load weights into selection** until holdout Δ > 0 on a retained checkpoint.

## Sources

| Artifact | Id / path |
|----------|-----------|
| Active diagnose | `wd_1783790309` · `artifacts/last_weights_diagnose.json` |
| Active holdout (prior) | `wh_1783787663` · [[2026-07-11-bw-holdout-wh-1783787663]] |
| Seed holdout | `wh_1783789773` · [[2026-07-11-bw-holdout-wh-1783789773]] |
| Seed train ckpt | `w_16f44b14ab36` (discarded) |
| Mutate confirm | `m_9b1d76cd30` · [[2026-07-11-mutate-m-9b1d76cd30]] |
| Soak | `soak_1783789768` |

## Next experiments

- [ ] Longer seed train (passes ≥ 8) with holdout gate still on  
- [ ] Different feature/ablation for phenotype net (research, not default)  
- [ ] Live evolve cycles under **Bc** only  
- [ ] Optional public note once a positive Bw−B0 appears  

→ [[Runs/README|Runs]] · [[Phase 6 Hardening]] · [[Phase 5 Population]] · [[System Map]]
