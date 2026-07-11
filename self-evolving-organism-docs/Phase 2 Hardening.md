---
tags: [phase/2, security, sandbox, hardening]
updated: 2026-07-11
---

# Phase 2 — Hardening review fixes

Applied from the Phase 2 hardening review (tiered). Frozen guardrails preserved.

## Tier 1 — Containment

| ID | Fix |
|----|-----|
| 1.1 | `organism.organism_api` facade; validate matches **full** `organism.*` path; deny config/sandbox/nim_client |
| 1.2 | Docker: `--cap-drop=ALL`, `no-new-privileges`, `--pids-limit`, `--user 1000:1000`; `/job` **ro**; result via `SEO_RESULT:` stdout; Dockerfile `USER seo` |
| 1.3 | `tests/test_sandbox_adversarial.py` — hostile imports, network block, read-only, timeout |

## Tier 2 — Correctness

| ID | Fix |
|----|-----|
| 2.1 | `episode_timeout_s` enforced in `run_episode` + docker_worker; outer timeout = N×ep×margin |
| 2.2 | `ChatResult` + `llm_calls` table + `cost_per_accepted_gain` tokens rollup |
| 2.3 | `manifest.py` → `*_manifest.json` on ablate/evolve (git SHA, pins, packages, seeds) |

## Tier 3 — Science

| ID | Fix |
|----|-----|
| 3.1 | `ablation_suite.repeats` K trajectories · mean±std on δ |
| 3.2 | Bcw code-only re-eval → `fitness_gain_from_weights` / `from_code`; train_passes aligned |

## Tier 4 — Polish

| ID | Fix |
|----|-----|
| 4.1 | `load_policy_class` cleans bare `sys.modules` aliases + unique modules |
| 4.2 | `critic.fail_open` config; distinct `fail_open` taxonomy code |
| 4.3 | `seo eval --ablation Bw` **requires** `--weights` |

## Smoke

| Check | Result |
|-------|--------|
| pytest | **49 passed** |
| Docker adversarial | network blocked · ro root · hardened eval |

## Post-ablation fixes (2026-07-11)

Live `abl_01d836c6d5` showed holdout **Bw ≈ 0.5 vs B0 ≈ 11** (weights replaced heuristics with random thrash).

| Fix | Effect (host holdout re-measure) |
|-----|----------------------------------|
| Heuristic BC bootstrap + engineered food features | boot-only ~8.9 |
| REINFORCE return-to-go + **keep-best** snapshot | no longer destroys BC |
| `explore_eval=0` | fair frozen policy eval |
| Schema AST: `obs.ticks`, `random.choice(weights=)` | catch live crash modes |
| SQL mutation memory → prompts | avoid repeat failures |

**After fix:** B0 holdout ~10.95 · Bw holdout ~**8.88** · Δ ≈ **−2.1** (still below B0, not catastrophic).

## Rebuild sandbox image

```powershell
seo docker-build
```

## See also

- [[Phase 2 Scaffold]]
- [[Phase 3 Critic]]
- [[Research Brief]]
