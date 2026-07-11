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

```powershell
seo doctor
seo doctor --strict-docker
```

## Checklist (in progress)

### Reliability

- [x] Operator console + job logs (Phase 4)
- [x] Windows UTF-8 job encoding
- [x] Mutate truncated-JSON recovery + retry
- [x] Dual-timescale **best-of phenotype** at Bw/Bcw eval
- [x] Weights holdout + diagnose + keep-if-beats-b0
- [ ] Longer-run soak tests (multi-hour evolve)
- [ ] Kernel regression suite gate in CI (optional)

### Isolation

- [x] Docker sandbox for candidate eval (Phase 2)
- [ ] Stricter parent isolation default (optional)
- [ ] Per-lineage Docker budgets (optional)

### Packaging & reproducibility

- [x] Manifests on evolve/ablate
- [x] Runs export from machine reports
- [ ] Single-command “reproduce last suite” bundle
- [ ] Signed/pinned seed + config snapshot archive

### Science extensions (open)

- [ ] Task curriculum / open-ended survival
- [ ] Hybrid body (sim + limited tools) — only if freeze allows
- [ ] Public research note packaging

## Immediate Phase 6 operator loop

1. `seo doctor` before long live runs  
2. Prefer **Bc** mutates + best-of eval for Bcw  
3. `seo weights diagnose` before trusting Bw  
4. `seo runs export` after every live suite  

## See also

- [[Roadmap]]
- [[Phase 5 Population]]
- [[Phase 4 Observer UI]]
- [[Home]]
