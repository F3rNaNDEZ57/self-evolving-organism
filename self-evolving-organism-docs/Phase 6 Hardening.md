---
tags: [phase/6, hardening]
updated: 2026-07-11
---

# Phase 6 — Hardening & open-ended experiments

## Goal

Research-grade reliability, packaging, and longer experiments — without redesigning the dual-timescale organism.

## Scaffold delivered

| Item | Status |
|------|--------|
| `seo doctor` health check | ☑ env / artifacts / docker / NIM key presence / control freeze |
| `artifacts/last_doctor_report.json` | ☑ |
| Phase 6 vault note + canvas | ☑ |
| Safety rail: default **Bc** when diagnose negative | ☑ `feat/safety-default-bc` |
| Soak harness (doctor-gated dry evolve) | ☑ `feat/phase6-soak-package` |
| Live soak + safety rail + fitness track | ☑ `feat/phase6-live-soak-ci` |
| UI Soak tab | ☑ Run → Soak |
| Kernel CI (pytest on push/PR) | ☑ `.github/workflows/kernel.yml` |
| Reproduce package (zip, no secrets) | ☑ `seo package` |
| Weights train/holdout **on seed** (experiment) | ☑ `feat/weights-train-seed` |

```powershell
seo doctor
seo doctor --strict-docker
seo soak --rounds 3
seo soak --live --rounds 5 --cycles 2 --max-mutations 2   # free NIM
seo package
seo weights train --on-seed --passes 4
seo weights holdout --on-seed --passes 2
```

## Safety rail (operator default)

When `artifacts/last_weights_diagnose.json` is missing or `recommend_use_weights=false`, mutate/evolve requested as **Bcw** is **downgraded to Bc** (code-only path). Override with `--force-bcw` only for intentional weight-path experiments.

## Soak + reproduce

| Command | Writes |
|---------|--------|
| `seo soak --rounds N` | `artifacts/last_soak_report.json` + `artifacts/soak/*.json` |
| `seo package` | `artifacts/reproduce/` (+ zip; excludes secrets) |

Soak runs doctor first (gate), then repeated **dry** evolve rounds — safe CI/operator health, not multi-hour live selection.

## Weights on seed (experiment only)

Does **not** train on the active lineage. Use to isolate weight-learning signal from evolved code:

```powershell
seo weights train --on-seed --passes 4    # keep-if-beats-b0 on by default for seed path
seo weights holdout --on-seed --passes 2
# UI: Run → Weights → checkboxes “seed genome (experiment)”
```

## Checklist (in progress)

### Reliability

- [x] Operator console + job logs (Phase 4)
- [x] Windows UTF-8 job encoding
- [x] Mutate truncated-JSON recovery + retry
- [x] Dual-timescale **best-of phenotype** at Bw/Bcw eval
- [x] Weights holdout + diagnose + keep-if-beats-b0
- [x] Safety default Bc when diagnose negative
- [x] Short soak harness (doctor + dry evolve)
- [x] Live soak flags + safety ablation + fitness first/last/best
- [x] Kernel regression suite gate in CI (`.github/workflows/kernel.yml`)
- [ ] Multi-hour operator soaks (run `seo soak --live --rounds N` as needed)

### Isolation

- [x] Docker sandbox for candidate eval (Phase 2)
- [ ] Stricter parent isolation default (optional)
- [ ] Per-lineage Docker budgets (optional)

### Packaging & reproducibility

- [x] Manifests on evolve/ablate
- [x] Runs export from machine reports
- [x] Single-command reproduce package (`seo package`)
- [ ] Signed/pinned seed + config snapshot archive

### Science extensions (open)

- [x] Seed-only weight train/holdout experiment path
- [x] Seed vs active weights A/B lab note ([[Runs/2026-07-11-seed-vs-active-weights-ab]])
- [x] Runs export for `diagnose` + `soak`
- [ ] Task curriculum / open-ended survival
- [ ] Hybrid body (sim + limited tools) — only if freeze allows
- [ ] Public research note packaging

## Immediate Phase 6 operator loop

1. `seo doctor` before long live runs  
2. Prefer **Bc** mutates (auto when diagnose negative) + best-of eval for Bcw  
3. `seo weights diagnose` before trusting Bw; seed experiments via `--on-seed`  
4. `seo soak` / `seo package` for health + shareable artifact bundle  
5. `seo runs export` after every live suite  

## Live ops suite (2026-07-11)

Confirmed end-to-end: doctor · soak · seed p8 train (discarded) · diagnose False · live evolve Bc rej · live mutate Bc rej · package · watch GIF · multi-lineage dry · critic-ab · docker-eval.

Active genome unchanged: `g_0a2b03eafe` @ ~28.13. See [[Runs/2026-07-11-seed-vs-active-weights-ab]].

## Live soak ×10 (2026-07-11 · `soak_1783791309`)

```powershell
seo soak --live --rounds 10 --cycles 2 --max-mutations 2 --ablation Bc
```

| Metric | Result |
|--------|--------|
| ok / doctor | True / True |
| mutations | **acc=0 / att=10** |
| fitness | 28.13 steady |
| genome | `g_0a2b03eafe` |

Note: [[Runs/2026-07-11-soak-soak-1783791309]]. Plateau under free NIM is expected with a strong parent; harness + safety rails held.

## See also

- [[Roadmap]]
- [[Phase 5 Population]]
- [[Phase 4 Observer UI]]
- [[Home]]
