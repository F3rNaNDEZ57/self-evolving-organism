---
tags: [phase/3, critic, nim, free-tier]
updated: 2026-07-11
---

# Phase 3 — Free NIM critic

## Goal

Gate genomic mutations with **static precheck + free NIM critic** before expensive Docker eval, reducing wasted episodes and unsafe patches.

## Design

```text
parent eval → propose (coder) → critic (static → NIM/dry) → apply → validate → eval → ε accept
                                      │ reject
                                      └─ skip Docker eval; log taxonomy
```

| Layer | Role |
|-------|------|
| `static_precheck` | Hard-fail: AST allowlist, Policy contract, size cap (500 lines) |
| `dry_run_critic` | Offline deterministic approve after static pass |
| Free NIM critic | Pin: `nvidia/nemotron-3-nano-30b-a3b` · JSON `approve|reject` + taxonomy |
| Fail-open | If NIM critic errors after static pass → low-confidence approve (logged) |

### Reject taxonomy

| Code | Meaning |
|------|---------|
| `approve` | Safe + plausibly useful |
| `unsafe_import` | Forbidden import / call |
| `contract_break` | Policy interface / whitelist |
| `low_value` | Empty / no-op |
| `overly_large` | Patch sprawl |
| `nonsense` | Invalid / incoherent |
| `other` | Misc reject |

## Config

```yaml
# config/experiment_v0.prereg.yaml
critic:
  enabled: true
  max_combined_lines: 500

# config/nim.pinned.yaml
models:
  critic: nvidia/nemotron-3-nano-30b-a3b
```

Env override: `NIM_CRITIC=...`

## CLI

```powershell
seo mutate --dry-run --ablation Bc          # dry critic + host eval
seo mutate --ablation Bc                    # live coder + live critic
seo mutate --no-critic --dry-run            # bypass critic gate
```

## Code map

| Path | Role |
|------|------|
| `src/organism/critic.py` | Verdict, static, dry, NIM review |
| `src/organism/mutation.py` | Critic gate before apply/eval |
| `src/organism/cli.py` | `--critic/--no-critic` |
| `tests/test_critic.py` | Static + dry + mutation reject path |

## Artifacts

- Critic reject: `artifacts/mutations/{id}_rejected_sources/` + `{id}.json` with `critic` blob
- Events: `mutation_critic`, `mutation_rejected` (via=critic)

## Smoke (2026-07-11)

| Check | Result |
|-------|--------|
| pytest | **20 passed** (incl. critic suite) |
| Seed genome | pathlib removed from whitelist `policy.py` (AST-clean) |
| Dry mutation + critic | approve → fitness gate |
| Unsafe proposal | `critic reject [unsafe_import]` · no eval |

## Remaining Phase 3

- [ ] Token/RPM budget counters + metrics (accept rate, wasted evals avoided)
- [ ] Live critic A/B vs no-critic (regression / waste rate)
- [ ] Summarizer distillation into critic context
- [ ] Router abstraction (plan / code / critique / summarize)

## See also

- [[Phase 2 Scaffold]]
- [[NIM Pin Log]]
- [[Roadmap]]
- [[Research Brief]]
