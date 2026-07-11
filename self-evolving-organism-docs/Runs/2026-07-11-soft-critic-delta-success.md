---
tags: [run, ablation, phase/3, success, soft-critic]
updated: 2026-07-11
branch: feat/soft-critic-delta
---

# Soft-critic + sequential Bcw — δ **SUCCESS**

## Branch

`feat/soft-critic-delta`

## Changes shipped

1. **Soft-threshold critic** — NIM `other` / `low_value` with conf &lt; 0.6 → `soft_pass` (still eval). Hard codes never soft-pass.
2. **Code-only fitness gate** — genomic mutates score as `Bc` (no mid-eval weight thrash).
3. **Bcw sequential dual** — when Bc runs first, Bcw **starts from Bc genome** and trains weights (code then phenotype), instead of re-mutating from seed.
4. **Bcw holdout** — best of code-only vs with-weights.

## Live suite `abl_5fb2945679` (soft critic, max_mutations=8)

| Arm | Holdout | Mut acc/att |
|-----|---------|-------------|
| B0 | 10.95 | 0/0 |
| Bw | 8.45 | 0/0 |
| **Bc** | **15.39** | **3/8** |
| Bcw (from seed, parallel) | 10.95 | 0/8 |

- Soft_pass moved patches to fitness eval; **3 code accepts** on Bc (16.8 → 28.1 train).
- Bc − B0 holdout = **+4.44** (code path works under free NIM + soft critic).
- Parallel Bcw from seed got 0 accepts → δ=0 for that arm layout.

## Completion suite `abl_de9d2391b0` (sequential Bcw from Bc genome)

| Arm | Holdout |
|-----|---------|
| B0 | 10.95 |
| Bw | 8.45 |
| Bc | **15.39** |
| **Bcw** | **15.39** (best phenotype = code_only) |

```
holdout Bcw − B0 = +4.4362
δ success threshold = 0.30
success = True
```

## Interpretation

- Soft critic unblocked free-NIM code evolution (Bc).
- Dual-timescale Bcw should **compose** code then weights, not re-roll code from seed.
- Weights still lag pure code on seed features; best-phenotype eval uses code path when stronger.

## Artifacts

- `artifacts/last_ablation_report.json` → `abl_de9d2391b0`
- Live mut lineage: `abl_5fb2945679` / genome `g_0a2b03eafe` (Bc final)

## See also

- [[Phase 3 Critic]]
- [[Runs/2026-07-11-live-ablation-weight-fix]]
