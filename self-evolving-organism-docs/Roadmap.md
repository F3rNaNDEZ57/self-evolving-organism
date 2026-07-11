---
title: Roadmap
tags:
  - project/roadmap
  - status/rnd
  - phase/0
aliases:
  - Project roadmap
  - Phases
status: active
updated: 2026-07-11
---

# Roadmap

> [!info] Living plan
> Phased R&D plan for [[Project Overview|self-evolving-organism]].  
> Canvas: [[System Map]] · Brief: [[Research Brief]] · Freeze: [[Open Decisions]] · Hub: [[Home]]

| Field | Value |
|-------|-------|
| Status | R&D · **Phase 0 freeze complete** · pre-implementation |
| Updated | 2026-07-11 |
| Related | [[System Map]] · [[Research Brief]] · [[Open Decisions]] · [[Artifact Management]] · [[References]] |

---

## Vision

Build a system of **self-evolving digital organisms** that:

1. Have a **body** (state + sensors + actuators) in a controlled environment
2. Accumulate **experience** and train **weights** (lifetime learning)
3. **Rewrite their own code** ([[Glossary#Genome|genome]]) under selection, assisted by a **free** [[Glossary#LLM pool|NIM LLM pool]]
4. Can be **monitored** (CLI/DB + Obsidian notes now; UI later): population, fitness, lineage, mutations, costs

> [!question] North-star
> What is the simplest organism that can improve its own code on a measurable task without escaping the sandbox?

---

## Guiding principles

| Principle | Meaning |
|-----------|---------|
| **R&D before product** | Freeze concepts and safety before scaling UI or population |
| **Empirical fitness** | Accept mutations only when evaluation improves (or meets explicit rules) |
| **Frozen kernel** | Sandbox, evaluator, host interfaces are **not** writable by organisms |
| **Lineage over vibes** | Every accepted change has parent, patch, metrics, cost |
| **Containment first** | No host FS/network by default; caps + kill switches |
| **Observe what you select** | If you cannot measure it, you cannot claim evolution |

---

## Core concepts

> [!tip] Full glossary
> Short table here; canonical defs in [[Glossary]].

| Term | One-liner |
|------|-----------|
| [[Glossary#Organism|Organism]] | Genome + body + memory + **weights** + policy + identity |
| [[Glossary#Genome|Genome]] | Mutable whitelist code modules |
| [[Glossary#Body|Body]] | Embodiment: energy, sensors, actuators |
| [[Glossary#Experience|Experience]] | Structured episode/mutation memory |
| [[Glossary#Weights (phenotype)|Weights]] | Fast trainable phenotype parameters |
| [[Glossary#Mutation|Mutation]] | Proposed code change, applied only after eval |
| [[Glossary#Fitness|Fitness]] | Frozen score over episodes/tasks |
| [[Glossary#LLM pool|LLM pool]] | Free NIM multi-model assistance |
| [[Glossary#Archive|Archive]] | Library of variants / lineage history |
| [[Glossary#Kernel|Kernel]] | Immutable experimental harness |

---

## Scope boundaries

### In scope (v0–v1 research)

- Single or small population in a **sandbox**
- Code self-modification of **allowed modules only**
- Simulated grid body + multi-seed fitness
- **Memory + weight training** + code mutation (ablations)
- NVIDIA NIM **free** OpenAI-compatible endpoints
- SQLite + disk artifacts + Obsidian lab notes
- CLI monitoring now; UI later; operator kill switch

### Explicit non-goals (early)

- Paid-only LLM as default
- Open internet for organisms
- Self-hosting / escaping the lab
- Training a foundation model (weights = small phenotype net only)
- Fancy 3D bodies before rewrite loop works
- Unbounded package install or host OS access
- Production multi-tenant SaaS

---

## Architecture

> [!tip] Prefer the canvas
> Interactive layout: [[System Map]]

```text
┌─────────────────────────────────────────────────────────┐
│ Monitor UI later · Obsidian Runs/ notes now             │
└──────────────────────────▲──────────────────────────────┘
                           │ events / metrics / ids
┌──────────────────────────┴──────────────────────────────┐
│ World / Environment (grid)                               │
└───────────────▲──────────────────────────▲──────────────┘
                │ act / sense              │ fitness
┌───────────────┴──────────┐    ┌──────────┴──────────────┐
│ Organism runtime         │    │ Evaluator (FROZEN)      │
│ genome + memory + weights│    │ multi-seed score        │
└───────────────▲──────────┘    └─────────────────────────┘
                │ propose patch (free NIM)
┌───────────────┴──────────────────────────────────────────┐
│ LLM Pool — free NIM endpoints only                        │
│ v0 coder → Phase 3 critic / summarizer / router           │
└──────────────────────────▲────────────────────────────────┘
                           │
┌──────────────────────────┴────────────────────────────────┐
│ Sandbox (subprocess + allowlist + timeouts)               │
└───────────────────────────────────────────────────────────┘
```

**Two loops (must stay distinct):**

1. **Behavioral (fast):** sense → act → reward → update **memory + weights**
2. **Genomic (slow):** trigger → free NIM patch → checks → sandbox eval → accept/reject → archive

---

## Phased roadmap

### Phase 0 — Concept freeze ✅

| | |
|--|--|
| **Goal** | Agree on the scientific object before product code |
| **Status** | **Complete** (owner freeze + canvas) |
| **Tags** | `#phase/0` |

**Deliverables**

- [x] Research brief → [[Research Brief]]
- [x] Decision freeze locked → [[Open Decisions]]
- [x] Success metrics + ablations (B0/Bw/Bc/Bcw)
- [x] Artifact / Obsidian pattern → [[Artifact Management]]
- [x] System canvas → [[System Map]]
- [x] Roadmap aligned with freeze

**Exit criteria** — met

- Written answers: organism, fitness, frozen kernel, mutable surface
- Body track: **sim grid**; dual learning + free NIM locked

---

### Phase 1 — Research package ✅

| | |
|--|--|
| **Goal** | Steal proven patterns; pin free NIM; lock containment + pre-reg |
| **Status** | **Complete** (2026-07-11) |
| **Tags** | `#phase/1` |

**Deliverables**

- [x] Comparison matrix → [[Phase 1 Research Package]]
- [x] Live NIM pins + chat smoke → [[NIM Pin Log]]
- [x] Docker `--network none` smoke **PASS**
- [x] Threat / containment recommendation (Docker)
- [x] Parameter pre-registration
- [x] Dashboard canvas updated → [[System Map]]

**Exit criteria** — met

- Must-steal mechanisms listed
- Free model ids verified on account
- Safety path (Docker) verified

---

### Phase 2 — Paper organism

| | |
|--|--|
| **Goal** | One organism that can improve under evaluation — **no fancy UI** |
| **Duration** | ~2–4 weeks |
| **Tags** | `#phase/2` |

**Scope**

- Tiny grid + mediocre seed genome
- Experience buffer + **small weight training**
- Single **free** NIM mutation path
- Sandbox → fitness → accept/reject
- Lineage in SQLite + artifacts; optional [[Runs/README|Runs/]] notes

**Deliverables**

- [x] Runnable episode runner + Docker smoke + SQLite logging → [[Phase 2 Scaffold]]
- [x] Frozen fitness implemented (pre-reg weights)
- [x] Weight checkpoint artifacts (`seo weights` + `artifacts/weights/`)
- [x] Lineage log tables (genomes/evaluations/episodes/events)
- [x] Mutation apply + accept/reject pipeline (`seo mutate`)
- [x] Ablation runs B0 / Bw / Bc / Bcw + holdout δ report (`seo ablate`)
- [x] Schedule + plateau auto-mutate (`seo evolve`)
- [x] Docker-isolated episode eval (`seo docker-build` / `docker-eval` / mutation candidates)
- [x] How-to-run / lab notes in vault `Runs/` → [[Runs/2026-07-11-live-ablation-weight-fix]]

**Exit criteria**

- Holdout **Bcw** improves vs **B0** (or **documented negative**) — **live free-NIM suites recorded**
  - pre-fix: δ=**−10.47** · post weight fix: δ=**−2.51** · success still **False** (max_mutations=3)
- Zero host escape on basic adversarial smoke tests — Docker smoke PASS · hardened flags

> [!example] Success metric
> Holdout fitness: Bcw ≥ B0 + δ; attribute gains via Bw and Bc.

**Smoke:** pytest **49p** · live ablate · weights BC/keep-best · Docker hardened

---

### Phase 3 — Free LLM pool + critic

| | |
|--|--|
| **Goal** | Multi-model quality control on **free NIM only** |
| **Duration** | ~2–3 weeks |
| **Tags** | `#phase/3` |

**Scope**

- Router: free models for plan / code / critique / summarize
- Critic rejects unsafe or low-value patches
- Budgets: tokens, RPM, mutations/generation
- Richer experience distillation

**Deliverables**

- [x] Free multi-model pins (coder / critic / summarizer) in `nim.pinned.yaml`
- [x] Critic policy + reject taxonomy (`src/organism/critic.py`)
- [x] Critic gate in mutation loop (before Docker eval)
- [x] Metrics: accept rate, critic reject rate, tokens/useful mutation (`seo metrics`)
- [x] Router abstraction + summarizer-enriched critic context
- [x] Offline critic A/B (`seo critic-ab`) for evals-saved estimate
- [x] Live free-NIM field trial (mutate · evolve · ablate) + [[Runs/2026-07-11-live-ablation-weight-fix]]
- [x] Mutation memory (SQL) + schema AST contracts
- [x] Soft critic `other`/`low_value` conf&lt;0.6 → soft_pass
- [x] Sequential Bcw (from Bc code) + best phenotype holdout
- [x] **δ success** Bcw − B0 = **+4.44** (`abl_de9d2391b0`) → [[Runs/2026-07-11-soft-critic-delta-success]]

**Exit criteria**

- Critic reduces wasted evals — **yes** (hard schema + soft_pass for noisy other)
- Free-tier RPM handled; model pins revalidated — **yes**
- **δ success** — **yes** under free NIM + soft critic + sequential dual timescale

**Smoke:** live soft-critic suite · Bc 3/8 accepts · sequential Bcw δ=+4.44

---

### Phase 4 — Observer UI

| | |
|--|--|
| **Goal** | Make the experiment legible to a human operator |
| **Duration** | ~2–3 weeks |
| **Tags** | `#phase/4` |

**Minimum surfaces**

- [x] Population / organism list (`seo ui` → Genomes)
- [x] Lineage tree (`seo ui` → Lineage)
- [x] Mutation inspector (scores, critic, tokens, sources)
- [x] Event timeline
- [x] Kill switch / pause / freeze (`artifacts/control.json`)

**Exit criteria**

- Operator can explain *why* fitness moved without only raw logs — **scaffold yes**
- UI stays read-mostly — not the organism brain — **yes**

**Launch:** `pip install -e ".[ui]"` · `seo ui` · [[Phase 4 Observer UI]]

**Operator console (decided 2026-07-11 · merged)**

- UI launches **CLI jobs** (not reimplemented science); dry-run default; single job; logs under `artifacts/jobs/`
- Slices: ☑ 4.1 job runner · ☑ 4.2 mutate/evolve/weights · ☑ 4.3 ablate/docker · ☑ 4.4 job history  
- Polish: ☑ live log fragment · ☑ launch plan (form vs history) · ☑ job params + final snapshot · ☑ Windows UTF-8 job env  
- Watch: ☑ live stream video · GIF loop · scrubber · `seo watch` GIF  
- Branches: `feat/phase4-run-from-ui` · `feat/watch-grid-replay` → **merged `master`**

---

### Phase 5 — Population dynamics

| | |
|--|--|
| **Goal** | Multiple organisms; selection and optional inheritance |
| **Duration** | ~3–5 weeks |
| **Tags** | `#phase/5` |

**Scope**

- Resource limits, selection, archive of elites
- Stronger isolation between organisms

**Scaffold (2026-07-11)**

- [x] Elite archive `artifacts/elites/registry.json` + `seo elite *`
- [x] Mutate parent picker (active / elite / genome) + `--parent-id` path fix
- [x] Genomes UI promote/demote · [[Phase 5 Population]]
- [x] Auto selection: `fitness_rank` / `tournament` (`feat/phase5-auto-selection`)
- [x] Evolve re-selects parent; auto-elite on accept when select≠active
- [x] Multi-lineage budgets + `run_evolve_population` (`feat/phase5-lineage-budgets`)
- [x] Multi-agent same-map Watch viz (`feat/phase5-multiagent-watch`)
- [x] Runs lab-note export (`seo runs export` · `feat/phase5-runs-export`)
- [x] Live mutate parse harden (truncated JSON + retry)
- [x] `seo weights holdout` B0 vs Bw holdout compare (`feat/bw-holdout-eval`)
- [x] Best-of phenotype at Bw/Bcw eval (`feat/best-of-phenotype-eval`)
- [x] Weights diagnose + keep-if-beats-b0 (`feat/weight-train-diagnostics`)

**Deliverables**

- [x] Solo vs population experiment write-up path (export stubs from evolve reports)
- [x] Operator path to measure Bw holdout gap
- [x] Dual-timescale best-of so weak scorers cannot tank code

**Exit criteria**

- Measurable diversity and/or continued improvement — or clear write-up of collapse

---

### Phase 6 — Hardening & open-ended experiments

| | |
|--|--|
| **Goal** | Research-grade reliability and broader questions |
| **Tags** | `#phase/6` |

**Scaffold + rails (2026-07-11)**

- [x] `seo doctor` environment health check · [[Phase 6 Hardening]]
- [x] Checklist: reliability / isolation / packaging / science extensions
- [x] Safety default **Bc** when weights diagnose negative (`feat/safety-default-bc`)
- [x] Soak harness + reproduce package (`feat/phase6-soak-package`)
- [x] Weights train/holdout **`--on-seed`** experiment path (`feat/weights-train-seed`)

**Scaffold + rails (continued)**

- [x] Seed vs active weight A/B lab note + export `diagnose`/`soak`

**Scaffold + rails (continued)**

- [x] Live soak hardening + UI Soak tab + kernel CI (`feat/phase6-live-soak-ci`)

**Candidates (next)**

- Longer operator live soaks (`seo soak --live --rounds N`)
- Stronger isolation defaults
- Optional public research notes
- Live evolve under Bc-only (weights still lag)

---

## Decision freeze (locked)

Canonical table: [[Open Decisions]] · detail: [[Research Brief#Decision freeze]] · canvas: [[System Map]]

| ID | Resolution |
|----|------------|
| D1 | Grid body |
| D2 | Task multi-seed fitness |
| D3 | Whitelist modules |
| D4 | Summaries + event subsample |
| D5 | Memory + **weights** + code mutation |
| D6 | NIM **free** endpoints only |
| D7 | SQLite + artifacts + Obsidian |
| D8 | Python |
| D9 | Subprocess-first sandbox |
| D10 | Single lineage |
| D11 | No UI in Phase 2 |
| D12 | Open-ended deferred |

---

## Safety checklist

Must remain true in every phase:

- [ ] Organisms cannot write evaluator or sandbox code
- [ ] No host FS outside sandbox workspace
- [ ] No network from organism runtime by default
- [ ] Mutation rate and population size capped
- [ ] Full audit log of proposed and applied patches
- [ ] Operator kill switch + freeze-mutations mode
- [ ] Budget ceilings (CPU, wall time, tokens, $)
- [ ] Reward hacking treated as first-class failure mode

Detail: [[Research Brief#Sandbox and safety]]

---

## Suggested metrics

| Metric | Why |
|--------|-----|
| Fitness over generations | Core claim of evolution |
| Accept / reject / crash rates | Pipeline health |
| Regression rate after accept | Eval quality |
| Tokens / $ per accepted gain | Economic viability |
| Lineage depth & diversity | Open-endedness vs collapse |
| Time-to-improve vs baseline | Value of self-rewrite |
| Sandbox violation attempts | Security signal |

---

## Milestone summary

| Phase | Name | Primary outcome | Status |
|------:|------|-----------------|--------|
| 0 | Concept freeze | Definitions + decisions + canvas | ✅ |
| 1 | Research package | Matrix + NIM pins + Docker + pre-reg | ✅ |
| 2 | Paper organism | Bcw vs B0 under sandbox | ✅ runner · ✅ δ success (sequential dual) |
| 3 | Free LLM pool + critic | Multi-model quality on free NIM | ✅ **soft critic · δ success** |
| 4 | Observer UI | Legible lineage & mutations + run console | ✅ **merged** |
| 5 | Population | Multi-organism selection | ✅ **scaffold** |
| 6 | Hardening | Research-grade isolation & experiments | 🔧 **doctor · soak · package · safety** |

---

## Immediate next steps

1. Multi-lineage live done (acc=0, critic low_value) — diversify slot parents / proposal modes
2. Keep **Bc** (weights holdout still negative)
3. `seo doctor` before long runs; `seo package` / `seo runs export` after suites
4. Weights only if holdout Δ > 0

---

## Document maintenance

- Update checkboxes and `updated` frontmatter when phases move
- Keep [[System Map]] in sync with architecture changes
- UI and multi-organism work are **not** blockers for Phase 2 success

---

## See also

[[Home]] · [[System Map]] · [[Project Overview]] · [[Research Brief]] · [[Open Decisions]] · [[Artifact Management]] · [[Glossary]] · [[References]]
