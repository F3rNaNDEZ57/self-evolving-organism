---
tags: [phase/3, critic, nim, free-tier, router, metrics]
updated: 2026-07-11
---

# Phase 3 — Free NIM pool + critic

## Goal

Multi-model quality control on **free NIM only**: critic gate, summarizer context, role router, budgets, and measurable waste reduction.

## Pipeline

```text
parent eval → summarize (distill) → propose (coder) → critic (static → NIM/dry)
                                                      │ reject → skip Docker eval
                                                      └ approve → apply → eval → ε
```

| Role | Pin (default) | Module |
|------|---------------|--------|
| code | `deepseek-ai/deepseek-v4-flash` | router → mutation |
| critique | `nvidia/nemotron-3-nano-30b-a3b` | critic |
| summarize | `meta/llama-3.1-8b-instruct` | summarizer |
| plan | summarizer pin | router alias |

## Layers

| Layer | Role |
|-------|------|
| `static_precheck` | Hard-fail AST / Policy contract / size |
| `dry_run_critic` | Offline approve after static |
| Free NIM critic | JSON approve/reject + taxonomy |
| Summarizer | Episode distill → coder + critic prompts |
| Router | role→pin + session token/call/mutation budgets |
| Metrics | accept rate, critic reject rate, evals saved, tokens/gain |

### Reject taxonomy

| Code | Meaning |
|------|---------|
| `approve` | Safe + plausibly useful |
| `unsafe_import` | Forbidden import / call |
| `contract_break` | Policy interface / whitelist |
| `low_value` | Empty / no-op |
| `overly_large` | Patch sprawl |
| `nonsense` | Invalid / incoherent |
| `fail_open` | NIM down, static-only pass |
| `other` | Misc reject |

## Config

```yaml
# experiment_v0.prereg.yaml
critic:
  enabled: true
  fail_open: true
  use_summarizer: true

pool:
  budget:
    max_rpm: 40
    max_tokens_session: 200000
    max_calls_session: 200
    max_mutations: 30
```

## CLI

```powershell
seo mutate --dry-run --ablation Bc
seo mutate --ablation Bc
seo mutate --no-critic --dry-run
seo metrics                    # accept rate, critic waste, tokens
seo critic-ab --n 6            # offline A/B: evals saved by critic
seo pins                       # role map + budget
```

## Code map

| Path | Role |
|------|------|
| `src/organism/critic.py` | Verdict + static/NIM |
| `src/organism/router.py` | FreeNimRouter + BudgetState |
| `src/organism/summarizer.py` | Episode distillation |
| `src/organism/metrics.py` | Pool rollup + critic A/B |
| `src/organism/mutation.py` | Summarize → propose → critic gate |
| `tests/test_phase3_pool.py` | Router/metrics/AB |

## Artifacts

- `artifacts/last_pool_metrics.json`
- `artifacts/last_critic_ab.json`
- Mutation meta: `critic`, `llm_usage`, `cost_per_accepted_gain_tokens`
- Events: `mutation_summarize`, `mutation_critic`

## Smoke

| Check | Result |
|-------|--------|
| pytest | **47+** (incl. phase3 pool) |
| `seo critic-ab` | evals saved on hostile proposals |
| `seo metrics` | rollup from SQLite |

## Deliverables

- [x] Free multi-model pins (coder / critic / summarizer)
- [x] Critic policy + reject taxonomy
- [x] Critic gate before Docker eval
- [x] Metrics: accept rate, critic reject rate, tokens/useful mutation
- [x] Router abstraction + summarizer-enriched critic context
- [x] Critic A/B (dry) for wasted-eval estimate
- [ ] Live long-run A/B with NIM (operator; needs key + RPM patience)

## See also

- [[Phase 2 Hardening]]
- [[NIM Pin Log]]
- [[Roadmap]]
