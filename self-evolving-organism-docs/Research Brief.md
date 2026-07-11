---
title: Research Brief
tags:
  - project/research
  - status/accepted
  - phase/0
aliases:
  - Phase 0 brief
  - Concept freeze
  - RESEARCH_BRIEF
status: accepted
updated: 2026-07-11
---

# Research Brief — Phase 0

> [!info] Purpose
> Freeze definitions, default decisions, experiment design, and safety rules **before** implementation.
>
> **Related:** [[System Map]] · [[Roadmap]] · [[Project Overview]] · [[Open Decisions]] · [[Artifact Management]] · [[Glossary]] · [[Home]]

| Field | Value |
|-------|-------|
| Status | Freeze accepted (owner amendments applied) |
| Updated | 2026-07-11 |
| Phase | `#phase/0` |

---

## Executive summary

We aim to build **embodied digital organisms** whose **behavior code** ([[Glossary#Genome|genome]]) improves under **empirical selection**, with mutations proposed via a **free** [[Glossary#LLM pool|NIM LLM pool]]. Organisms accumulate [[Glossary#Experience|experience]], train small [[Glossary#Weights (phenotype)|weights]], act through a [[Glossary#Body|body]], and are observed via CLI/DB + this vault (UI later).

Visual: [[System Map]].

### v0 defaults (frozen)

| Choice | v0 default |
|--------|------------|
| Body | **Simulated grid world** (minimal ALife-style) |
| Goal style | **Task-driven fitness** (measurable episode score) |
| Mutable surface | **Whitelist modules only** |
| Learning | **Memory + trainable weights** (fast) **+** slow code mutation (see D5) |
| LLM | **NVIDIA NIM free endpoints only**; single free coder first, pool later |
| Persistence | **SQLite + disk artifacts + Obsidian lab notes** |
| Population | **Single organism lineage** first |

> [!question] North-star
> What is the simplest organism that can improve its own code on a measurable task without escaping the sandbox?

---

## Problem statement

### Motivation

Most agent systems have a **fixed architecture**. Self-improvement is usually limited to prompt tweaks, retries, or external fine-tuning.

We want:

1. Act through a body  
2. Record experience  
3. Rewrite allowed code (LLM-assisted)  
4. Validate in a sandbox  
5. Archive successful variants with full lineage  

### Research questions

| ID | Question |
|----|----------|
| RQ1 | Can sandboxed code mutation raise fitness faster than a non-mutating baseline? |
| RQ2 | What experience form best improves mutation quality? |
| RQ3 | Does a critic model reduce regressions enough to justify cost? |
| RQ4 | How often do mutations attempt violations (escape, reward hack, loops)? |
| RQ5 | (Later) Does population + archive beat single-lineage hill-climbing? |

### Non-questions (v0)

- Open-ended AGI / unrestricted self-replication on the host  
- Training a new foundation model  
- Photorealistic or 3D embodiment  
- Multi-tenant production deployment  

---

## Conceptual model

### Organism = five parts

```text
Organism
├── Identity     id, generation, parent_id, created_at
├── Genome       versioned code modules (mutable whitelist)
├── Body         position, energy, inventories, budgets, status
├── Memory       experience log + optional distilled lessons
├── Weights      small trainable phenotype (fast learning)
└── Runtime hook sense → decide → act  (genome + weights)
```

> [!abstract] Definition (frozen for v0)
> An **organism** is a sandboxed agent with a versioned **genome** (code), a **body** in a simulated world, structured **memory**, **trainable weights**, and a **lineage identity**. It may request genome mutations; only the frozen **kernel** may apply them after evaluation.

See [[Glossary#Organism]].

### Kernel vs organism

| Layer | Mutable by organism? | Role |
|-------|----------------------|------|
| **Kernel** | **No** | World, sandbox, evaluator, LLM client, DB, operator controls |
| **Genome** | **Yes (whitelist)** | Policy, heuristics, local helpers |
| **Weights** | Yes (tensors / checkpoints) | Lifetime learning phenotype |
| **Memory** | Yes (data) | Traces, summaries, scores |
| **Body state** | Via legal actions only | Updated by world rules |

> [!danger] Critical
> If the organism can edit the evaluator or sandbox, the experiment is **invalid**.

### Two timescales

| Loop | Rate | What changes | Success signal |
|------|------|--------------|----------------|
| **Behavioral** | Every tick | Body, memory, **weights** | Immediate reward / survival |
| **Genomic** | Rare | Code modules | Fitness on eval episodes |

Do **not** conflate “LLM thought harder” with “organism evolved.”  
**Evolution** = accepted genome change + lineage record.

---

## Body and environment (v0)

### Default track: minimal grid world

**Why first**

- Visually “alive” (body, energy, position)  
- Easy to score and reproduce  
- Naturally sandboxed  
- Extends cleanly to populations later  

### World sketch

| Element | Spec |
|---------|------|
| Topology | 2D grid, e.g. 16×16 or 32×32 |
| Time | Discrete ticks; episode length `T` (e.g. 100–500) |
| Resources | Food cells; optional hazards |
| Body state | `(x, y)`, `energy`, `alive`, optional inventory |
| Actions | `move_n/s/e/w`, `forage`, `rest`, `noop` |
| Sensors | Local view (3×3 or 5×5), energy, tick, last reward |
| Death | `energy <= 0` or timeout |
| Randomness | Seeded RNG |

**Episode:** reset → run policy ≤ `T` ticks → fitness → store summary.

### Alternative tracks (deferred)

| Track | When to revisit |
|-------|-----------------|
| Process body (tools, coding tasks) | After mutation pipeline proven (DGM-like) |
| Hybrid (sim + limited tools) | Phase 5–6 if sim plateaus |

### Embodiment requirements

Any body must provide: **state**, **actions**, **budgets**, **failure modes** that affect fitness.

---

## Genome design

### Module whitelist (v0)

| Module | Responsibility | Mutate? |
|--------|----------------|---------|
| `policy.py` | Observation → action | Yes |
| `heuristics.py` | Move scoring / utilities | Yes |
| `memory_hooks.py` | Experience read/write for decisions | Yes (careful) |
| `interface.py` | Obs/action schemas | **No** |
| Kernel packages | World, sandbox, eval, LLM, DB | **No** |

### Interface contract (frozen)

```text
class Policy:
    def reset(self, seed: int) -> None: ...
    def act(self, observation: Observation) -> Action: ...
    def on_step_result(self, result: StepResult) -> None: ...
```

- Schemas defined by kernel  
- Genome only imports approved `organism_api` facade  
- Forbidden (enforced by sandbox): `os`, `subprocess`, `socket`, unchecked `eval`/`exec`, host FS  

### Seed organism

Ship a **deliberately mediocre** baseline (random walk or naive greedy food chase).  
If the seed is near-optimal, mutation has nothing to show.

### Variant record

```text
genome_id
parent_genome_id | null
module_hashes
source snapshot or patch set
created_at
mutation_prompt_id / llm_meta
eval_scores
status: candidate | accepted | rejected | crashed
```

---

## Experience and memory

### Layers

| Layer | Content | Used for |
|-------|---------|----------|
| Event log | tick, obs summary, action, reward, energy Δ | Replay, debug |
| Episode summary | totals, survival, death cause, failures | Mutation prompts |
| Distilled lessons | Short notes (optional v0.5+) | Better rewrite context |
| Mutation memory | Past patches + accept/reject + Δ score | Avoid repeat failures |

### Budgets

- Cap events per episode  
- Cap total memory bytes  
- Prefer rolling windows + summaries  

### Experience → mutation prompt

1. Last `K` episode summaries (+ lessons)  
2. Current allowed module sources  
3. Fitness trend + recent rejected patches  
4. Coder model: **minimal patch** + rationale  
5. Critic (Phase 3+) → sandbox eval  

---

## Fitness and evaluation

### Design rules

1. Only the **frozen evaluator** computes fitness  
2. Reproducible given seed + genome + world config  
3. Multi-seed eval to reduce lucky mutations  
4. Publish the formula (secret fitness = anti-research)  

### Proposed v0 fitness (grid)

Run `N` episodes (e.g. 5–10) with seeds `s1..sN`:

```text
episode_score = w1 * total_food_collected
              + w2 * ticks_survived / T
              + w3 * final_energy / energy_max
              - w4 * invalid_actions
              - w5 * wall_bumps

fitness = mean(episode_score) - λ * score_variance
```

Weights are **kernel config**, not genome-editable.

### Acceptance rule

```text
fitness(candidate) >= fitness(parent) + ε
AND crash_rate == 0 on eval seeds
AND no sandbox policy-violation flags
```

| Parameter | Suggested start |
|-----------|-----------------|
| `ε` | ~1% of parent fitness or absolute 0.01 |
| `N` | 5–10 episodes |
| Timeout | Fixed wall/CPU per episode |

**Reject** on: lower fitness, crash, timeout, sandbox violation, contract break, critic hard-fail (Phase 3+).

### Baselines (required for claims)

| ID | Description |
|----|-------------|
| **B0** | Fixed seed — no mutation, no weight training |
| **Bw** | Fixed code + weight training only |
| **Bc** | Code mutation (LLM), weights reset / no train |
| **Bcw** | Full system: experience + code mutation + weight training |
| **B1** | Random patches (optional ablation) |
| **B2** | LLM mutates without experience context (optional) |

Claim “dual learning works” only with ablations: e.g. **Bcw** vs **B0**, and ideally **Bcw** vs **Bw** and **Bc**, under the same budget.

### Reward-hacking watchlist

| Failure | Symptom | Mitigation |
|---------|---------|------------|
| Survival farming | High survive, zero food | Balance weights; thresholds |
| Action gaming | Invalid actions inflate score | Penalties + hard reject |
| Seed overfitting | Great on train seeds only | Hold-out seeds |
| Infinite loop | Hang | Timeouts; score 0 |
| Env oracle | Illegal imports / map peek | Import allowlist |

---

## Mutation protocol

### Triggers

| Trigger | Example |
|---------|---------|
| Schedule | Every `M` episodes |
| Plateau | No gain for `P` episodes |
| Failure burst | High death / crash-like behavior |
| Operator | Manual “mutate now” |
| Energy surplus | Optional flavor gate |

> [!tip] v0 recommendation
> **Schedule + plateau**.

### Steps

```text
1. Snapshot parent genome + fitness
2. Build mutation context
3. LLM coder proposes patch (whitelist only)
4. Static checks: parse, imports, interface
5. (Phase 3+) Critic approve/reject
6. Sandbox eval suite
7. Compare scores → accept or reject
8. Persist lineage + costs; emit events
9. On accept: promote candidate; archive parent
```

### Patch constraints

- Whitelist paths only  
- Size caps; prefer small diffs  
- One logical change when possible  
- Text source only  

### Rollback

- Always keep parent artifact  
- Active pointer moves only on accept  
- Operator can force-rollback to any `genome_id`  

---

## LLM pool (NVIDIA NIM)

### Roles

| Role | Job | Phase |
|------|-----|-------|
| Coder | Propose patches (**free** NIM model) | v0 |
| Critic | Safety / contract / regression review (free model) | Phase 3 |
| Summarizer | Distill experience (free model) | Phase 3 (optional earlier) |
| Router | Choose free model by task / budget / RPM | Phase 3 |

> [!note]
> LLMs are **not** the organism. They are external kernel services.

### Integration assumptions

- OpenAI-compatible HTTP API  
- Config via env (base URL, key, model names)  
- Log prompts/responses (redact secrets)  
- Hard caps: tokens, $, mutations/hour  

### Prompting principles

1. Always include interface contract + forbidden APIs  
2. Source + metrics, not “be better”  
3. Ask for minimal patch + short rationale  
4. Include recent failed mutations  
5. Never give credentials, host paths, or kernel source  

### Cost metric

```text
tokens_in, tokens_out, estimated_usd, latency_ms, model_id
cost_per_accepted_gain = total_usd / max(fitness_gain, ε)
```

---

## Sandbox and safety

### Threat model (v0)

| Threat | Example | Severity |
|--------|---------|----------|
| Host escape | Write outside jail, spawn processes | Critical |
| Network exfil | Call home | Critical |
| Kernel sabotage | Edit evaluator | Critical |
| Resource exhaustion | Infinite loop, huge alloc | High |
| Reward hacking | Proxy metric abuse | High |
| Cost attack | Mutation spam | Medium |
| Deceptive reporting | Multi-agent later | Medium (later) |

### Containment controls

| Control | Requirement |
|---------|-------------|
| Process isolation | Restricted subprocess / container / Wasm ([[Open Decisions|D9 open]]) |
| Import allowlist | Approved modules only |
| No network | Block organism outbound |
| FS jail | Temp workspace per candidate |
| Time/memory limits | Hard kill |
| Mutation rate limits | Cap concurrent + daily |
| Operator controls | Pause, freeze mutations, kill, rollback |

### Safety invariants

1. No organism writes to kernel / evaluator / sandbox  
2. No host home, secrets, or network by default  
3. Every genome change is auditable  
4. Max wall-clock and spend per experiment  
5. Kill switch works even if policy loops (kernel-side)  

### Digital biosafety stance

> [!warning] Lab experiment framing
> Prefer **breeder mode** (human-defined fitness, controlled reproduction) over uncontrolled ecosystem mode early on. No autonomous self-deployment outside the project sandbox. Population only under explicit caps (Phase 5).

---

## Observability and UI

Even before Phase 4 UI, emit UI-ready data.

### Minimum event schema

```text
event_id, ts, organism_id, genome_id, type, payload_json
types: step, episode_end, mutation_proposed, mutation_accepted,
       mutation_rejected, crash, sandbox_violation, operator_action
```

### Phase 4 monitor views

1. Organism status  
2. Lineage  
3. Diff viewer  
4. Fitness charts  
5. LLM cost  
6. Operator controls  

### v0 without UI

CLI + SQLite + JSONL is fine if schemas match future UI.

---

## Persistence model (v0)

**Store:** SQLite + `artifacts/` (source + weight checkpoints) + Obsidian lab notes — see [[Artifact Management]].

| Table | Key fields |
|-------|------------|
| `organisms` | id, name, status, active_genome_id |
| `genomes` | id, parent_id, status, created_at, artifact_path |
| `evaluations` | genome_id, fitness, metrics_json, seeds |
| `mutations` | parent/candidate, prompt, decision, reason |
| `episodes` | genome_id, seed, score, summary_json |
| `events` | ts, type, payload_json |
| `llm_calls` | mutation_id, model, tokens, cost, latency |

**Reproducibility package:** config, seed source, RNG roots, genome chain, library versions.

---

## v0 experiment design (“paper organism”)

### Hypothesis

> Under fixed eval budget, experience-conditioned LLM mutations to `policy.py` produce higher final fitness than a non-mutating baseline of the same seed policy.

### Procedure

1. Fix world, weights, `S_train`, holdout `S_holdout`  
2. Run **B0**, **Bw**, **Bc**, **Bcw** under matched budgets where possible  
3. Emphasize **Bcw** vs **B0**; use **Bw** / **Bc** to attribute gains  
4. Evaluate finals on holdout seeds  
5. Record costs, violations, and weight checkpoint hashes  

### Success criteria (Phase 2 exit)

| Result | Interpretation |
|--------|----------------|
| Holdout Bcw ≥ B0 + δ | Positive signal for full system → Phase 3 |
| Bcw ≈ Bw ≫ Bc | Weights carry gains; code mutation weak — improve prompts/genome surface |
| Bcw ≈ Bc ≫ Bw | Code mutation carries gains; keep weights as optional polish |
| Bcw ≈ B0 | Inconclusive → revise experience/prompts/difficulty |
| High crash / critical sandbox violations | Stop features → harden isolation |

Pre-register `δ` in config.

### Difficulty dial

Sparse food, energy drain, limited vision, optional hazards.  
If random walk hits the ceiling, **make the world harder** before claiming evolution failed.

---

## Decision freeze

> [!success] Owner freeze applied 2026-07-11
> Canonical tracker with full amendment notes: [[Open Decisions]]. Artifact layout: [[Artifact Management]].

| ID | Decision | Status | Resolution |
|----|----------|--------|------------|
| D1 | Body track v0 | **Accepted** | Simulated grid world |
| D2 | Goal style | **Accepted** | Task-driven multi-seed fitness |
| D3 | Mutable surface | **Accepted** | Whitelist: policy / heuristics / memory_hooks |
| D4 | Experience form | **Accepted** | Episode summaries + event subsample |
| D5 | Individual learning | **Changed** | Memory + **trainable weights** + code mutation (ablations required) |
| D6 | LLM provider | **Changed** | NVIDIA NIM **free endpoints only**; OpenAI-compatible client |
| D7 | Persistence | **Changed** | SQLite + disk artifacts + Obsidian lab notes |
| D8 | Language runtime | **Accepted** | Python |
| D9 | Isolation tech | **Accepted** | Subprocess + allowlist + timeouts first |
| D10 | Population size v0 | **Accepted** | 1 active lineage |
| D11 | UI in Phase 2 | **Accepted** | No — CLI + DB only |
| D12 | Open-ended survival sole fitness | **Deferred** | Phase 5+ |

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Useless verbose rewrites | Diff caps, critic, few-shots |
| Fitness too easy/hard | Difficulty dial; pilots |
| Eval seed overfitting | Holdout seeds |
| Weak Windows sandbox | Strong isolation early |
| Scope creep | [[Roadmap]] phase gates |
| Cost blowups | Hard $ and mutation caps |
| Fake evolution demos | Require genome_id change + score Δ |

---

## Deliverables tied to this brief

| Deliverable | Phase |
|-------------|------:|
| This brief accepted | 0 |
| Decisions / ADRs for D1–D12 | 0 exit |
| Literature comparison matrix | 1 |
| Expanded threat model | 1 |
| Runnable paper organism | 2 |
| Multi-model pool + critic | 3 |
| Monitor UI | 4 |
| Population dynamics | 5 |

---

## Recommended next actions

1. Review this brief — Accept / Change each decision  
2. Resolve [[Open Decisions]] (D8, D9)  
3. Write formal Decisions log after accept  
4. Phase 1 survey using [[References]]  
5. Only then scaffold Phase 2  

---

## Approval

| Role | Name | Date | Verdict |
|------|------|------|---------|
| Project owner | | 2026-07-11 | **Accept with changes** (D5, D6, D7) |
| Notes | Dual learning + free NIM + Obsidian artifacts; rest as proposed | | |

Full amendment record: [[Open Decisions]].

---

> [!success] Gate
> Phase 0 freeze is **accepted**. Phase 2 may start after Phase 1 survey prep and free model pinning — not before sandbox design is clear.

## See also

[[Home]] · [[System Map]] · [[Project Overview]] · [[Roadmap]] · [[Open Decisions]] · [[Artifact Management]] · [[Glossary]] · [[References]]
