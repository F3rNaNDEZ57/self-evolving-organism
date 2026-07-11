---
title: Open Decisions
tags:
  - project/decisions
  - status/accepted
  - phase/0
aliases:
  - Decisions tracker
  - Decision freeze
  - D1-D12
status: accepted
updated: 2026-07-11
---

# Open Decisions

> [!success] Phase 0 freeze — owner feedback applied
> Most rows **Accepted**. Amendments: **D5** (weights + memory), **D6** (free NIM models), **D7** (SQLite + artifacts + Obsidian lab notes).
>
> Canvas: [[System Map]] · Brief: [[Research Brief#Decision freeze]] · Overview: [[Project Overview]] · Artifacts: [[Artifact Management]]

---

## Legend

| Status | Meaning |
|--------|---------|
| **Proposed** | Default in brief (historical) |
| **Open** | Unresolved |
| **Deferred** | Not v0 |
| **Accepted** | Locked for v0 |
| **Changed** | Accepted with a different resolution than original proposal |

---

## Decision table (locked)

| ID | Decision | Status | Resolution |
|----|----------|--------|------------|
| D1 | Body track v0 | **Accepted** | Simulated grid world |
| D2 | Goal style | **Accepted** | Task-driven multi-seed fitness |
| D3 | Mutable surface | **Accepted** | Whitelist: policy / heuristics / memory_hooks |
| D4 | Experience form | **Accepted** | Episode summaries + event subsample |
| D5 | Individual learning | **Changed** | **Memory + trainable weights** (dual timescale; see below) |
| D6 | LLM provider | **Changed** | **NVIDIA NIM free endpoints only** (OpenAI-compatible); pool from free catalog |
| D7 | Persistence | **Changed** | **SQLite + file artifacts + Obsidian lab notes** |
| D8 | Language runtime | **Accepted** | **Python** |
| D9 | Isolation tech | **Accepted** | **Subprocess + allowlist + timeouts** first; harden later |
| D10 | Population size v0 | **Accepted** | 1 active lineage (archive parents) |
| D11 | UI in Phase 2 | **Accepted** | No — CLI + DB only |
| D12 | Open-ended survival as sole fitness | **Deferred** | Phase 5+ |

---

## Amendment detail

### D5 — Memory + weight training (Changed)

**Owner ask:** train weights as well as store experience / mutate code.

**Verdict:** **Yes — with a dual-inheritance design** so science stays interpretable.

| Timescale | What changes | Analogy |
|-----------|--------------|---------|
| **Fast (lifetime)** | Weights + memory within an episode / generation | Learning / adaptation |
| **Slow (evolution)** | Whitelist genome code via LLM + eval | Genetic change |

**Design rules (locked for v0)**

1. **Weights are phenotype, not kernel** — small learnable module (e.g. tiny net / linear scorer) owned by the organism; checkpoints are artifacts.
2. **Code defines the learning algorithm + architecture hooks** — mutations can change *how* weights update or how features are built; kernel still freezes fitness.
3. **Ablations required** before claiming “self-evolution works”:
   - **B0** fixed code, no weight train  
   - **Bw** fixed code + weight train  
   - **Bc** code mutation, weights reset / no train  
   - **Bcw** code mutation + weight train (full system)  
4. Keep weight modules **small** (toy grid does not need a large net). Prefer simple RL / bandit / value-head style updates over full LLM fine-tunes.
5. Log separately: `fitness_gain_from_weights` vs `fitness_gain_from_code` when possible (e.g. re-eval with weights zeroed / re-init).

> [!warning] Attribution
> If you only run Bcw, you will not know whether the LLM patches or the weight training carried the win. Ablations are not optional for research claims.

---

### D6 — Free NVIDIA NIM models (Changed)

**Owner ask:** use free-of-charge models available on NVIDIA NIM.

**Verdict:** **Yes.** Client targets [build.nvidia.com](https://build.nvidia.com/) free / Free Endpoint catalog via OpenAI-compatible API.

| Field | Value |
|-------|--------|
| Base URL (typical) | `https://integrate.api.nvidia.com/v1` |
| Auth | NVIDIA API key (`nvapi-…`) from developer / build.nvidia.com |
| Constraint | **Prefer free-endpoint models only** for default configs; no paid-only models in v0 defaults |
| Rate limits | Expect RPM limits (commonly cited ~40 rpm); design mutation loop with backoff + queue |

**Role → model strategy (IDs change over time — pin in config, re-check catalog)**

| Role | Prefer | Examples from catalog (verify “Free Endpoint” on site) |
|------|--------|--------------------------------------------------------|
| **Coder** (patches) | Strong coding / agentic free models | `deepseek-v4-flash`, `mistral-nemotron`, `glm-5.2`, `minimax-m2.7`, `nemotron-3-nano-30b-a3b` |
| **Critic** (Phase 3) | Smaller / faster free model | `gpt-oss-20b`, `llama-3.1-8b-instruct`, `gemma-2-2b-it` |
| **Summarizer** | Cheap free instruct | small Llama / Gemma / Nemotron nano family |

> [!tip] Catalog is live
> Free vs paid labels and model names **move**. Config should list `model_id` + `requires_free: true` and fail loudly if a model is no longer free. Re-validate against [build.nvidia.com/models](https://build.nvidia.com/models) before long runs.

**v0 pool shape:** start with **one free coder**; add free critic/summarizer in Phase 3 without changing the API client.

---

### D7 — SQLite + artifacts + Obsidian (Changed)

**Owner ask:** Accept SQLite + artifacts; also use Obsidian for artifact management.

**Verdict:** **Yes — split machine store vs human lab notebook.**

| Layer | Store | Holds |
|-------|--------|--------|
| **Operational DB** | SQLite | organisms, genomes, evals, mutations, events, llm_calls (queryable) |
| **Binary / source artifacts** | `artifacts/` on disk | genome source snapshots, weight checkpoints (`.pt` / `.npz`), diffs, raw logs |
| **Human lab notebook** | **This Obsidian vault** | run reports, lineage narratives, decision notes, links to artifact paths + genome ids |

**Obsidian is great for**

- Experiment run notes (`Runs/YYYY-MM-DD-short-name.md`)
- Mutation post-mortems (why accepted/rejected)
- Lineage stories and research insights
- Embedding charts/screenshots later
- Linking `genome_id` ↔ note via frontmatter

**Obsidian is not the primary store for**

- High-frequency step events  
- Binary weight tensors  
- Anything the runtime must query in a tight loop  

> [!example] Pattern
> Runtime writes SQLite + `artifacts/genomes/{id}/…`  
> Optional export / script creates or updates a vault note under `Runs/` with frontmatter:
> `genome_id`, `parent_id`, `fitness`, `artifact_path`, `nim_model`, `weights_path`

See also: [[Artifact Management]]

---

## Amendment log

| Date | ID | Old | New | Why |
|------|----|-----|-----|-----|
| 2026-07-11 | D5 | Memory only | Memory + trainable weights | Owner: dual learning (lifetime + evolution) |
| 2026-07-11 | D6 | Single generic NIM coder | Free NIM endpoints only; multi-role free pool later | Owner: zero $ inference preference |
| 2026-07-11 | D7 | SQLite + artifacts | SQLite + artifacts + Obsidian lab notes | Owner: human-facing artifact / run management |
| 2026-07-11 | D1–D4, D8–D12 | Proposed / Open / Deferred | Accepted as table | Owner: rest of freeze OK |

---

## Still true (unchanged package)

- Sim grid body, task fitness, whitelist genome, single lineage, CLI-first, Python, subprocess sandbox first  
- Kernel / evaluator frozen  
- Phase 2 exit still needs baselines — now including weight ablations  

---

## Gate status

- [x] Proposed rows accepted or changed  
- [x] D8 resolved (Python)  
- [x] D9 resolved (subprocess-first)  
- [x] Owner amendments recorded  
- [ ] Formal [[Research Brief#Approval|Approval]] block signed (optional ceremony)

**Phase 2 scaffolding is unblocked.** Free NIM pins + Docker smoke verified 2026-07-11 → [[NIM Pin Log]] · [[Phase 1 Research Package]].

---

## See also

[[Home]] · [[System Map]] · [[Project Overview]] · [[Research Brief]] · [[Roadmap]] · [[Glossary]] · [[Artifact Management]] · [[References]]
