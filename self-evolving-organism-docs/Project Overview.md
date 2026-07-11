---
title: Project Overview
tags:
  - project/overview
  - status/rnd
  - phase/0
aliases:
  - Overview
  - About this project
  - README
status: active
updated: 2026-07-11
---

# Project Overview

> [!info] Living overview
> High-level picture of **self-evolving-organism**.  
> Visual: [[System Map]] · Design: [[Research Brief]] · Plan: [[Roadmap]] · Freeze: [[Open Decisions]]

---

## One-liner

Build **self-evolving digital organisms** with bodies, **experience + trainable weights**, **LLM-assisted code rewriting** (NVIDIA NIM **free** endpoints), and later a **monitor UI** — under hard sandboxing and empirical fitness.

---

## Why this project exists

Most agent stacks are **fixed architectures**: humans design the loop; models only fill prompts and tool calls. We want a tighter loop:

1. Organism **acts** through a **body** in a controlled world  
2. It stores **experience** and trains **weights** (lifetime learning)  
3. With free NIM help, it **rewrites allowed genome code** (evolution)  
4. Changes are **tested in a sandbox** and kept only if fitness improves  
5. Humans **observe** lineage, diffs, costs, weights, and failures (CLI → later UI; notes in this vault)

Intersection of: self-improving agents (DGM), artificial life (Avida), NIM inference, evolvable-AI safety — see [[References]].

---

## Four pillars

| Pillar | Meaning | v0 stance |
|--------|---------|-----------|
| **Body** | State + sensors + actuators | Simulated grid world |
| **Experience + weights** | Memory + fast parameter learning | Summaries + small trainable module |
| **Self-rewrite** | Genome under selection | Whitelist modules + sandbox eval |
| **Observe** | Humans can monitor and stop | CLI/DB first; Obsidian run notes; UI Phase 4 |

---

## North star

> [!question]
> What is the simplest organism that can improve its own code on a measurable task **without escaping the sandbox**?

---

## What an organism is

```text
Organism
├── Identity     id, generation, parent, timestamps
├── Genome       versioned whitelist code (slow evolution)
├── Body         position, energy, status, budgets
├── Memory       experience summaries / events
├── Weights      small trainable phenotype (fast learning)
└── Policy hook  sense → decide → act  (code + weights)
```

[[Glossary]] · [[Research Brief#Conceptual model]] · [[System Map]]

---

## Kernel vs genome (non-negotiable)

| Layer | Organism can edit? | Role |
|-------|--------------------|------|
| **Kernel** | No | World, sandbox, evaluator, LLM client, DB, kill switch |
| **Genome** | Yes (whitelist) | Policy / heuristics / memory hooks |
| **Weights** | Yes (data / tensors) | Lifetime learning checkpoints |
| **Memory** | Data only | Logs and summaries |
| **Body state** | Via legal actions | Updated by world rules |

> [!warning] Invalid experiment
> If the organism can edit the **evaluator** or **sandbox**, results do not count.

---

## Two loops

| Loop | Speed | Changes | Success signal |
|------|-------|---------|----------------|
| **Behavioral** | Every tick | Body, memory, **weights** | Reward / survival |
| **Genomic** | Rare | Code modules | Multi-seed fitness + lineage |

**Evolution** = accepted genome change + lineage record + score delta — not “the LLM reasoned longer.”  
**Learning** = weight updates within a generation — attribute via ablations (B0 / Bw / Bc / Bcw).

---

## Target architecture

```text
┌─────────────────────────────────────────┐
│ Monitor UI later · Obsidian notes now   │
└──────────────────▲──────────────────────┘
                   │ events / ids
┌──────────────────┴──────────────────────┐
│ World / Environment (grid)              │
└─────────▲──────────────────▲────────────┘
          │ act/sense        │ fitness
┌─────────┴────────┐  ┌──────┴────────────┐
│ Organism runtime │  │ Evaluator FROZEN  │
│ genome+mem+wts   │  └───────────────────┘
└─────────▲────────┘
          │ patch (free NIM)
┌─────────┴───────────────────────────────┐
│ LLM Pool — free NIM endpoints only      │
└─────────▲───────────────────────────────┘
          │
┌─────────┴───────────────────────────────┐
│ Sandbox (subprocess + allowlist)        │
└─────────────────────────────────────────┘
```

Full canvas: [[System Map]]

---

## Current status

| Item | Status |
|------|--------|
| Phase | **0 freeze accepted** → Phase 1 / 2 prep |
| Codebase | Greenfield |
| Canvas | [[System Map]] |
| Next | Phase 1 survey; pin free NIM model IDs; then Phase 2 scaffold |

### Done

- [x] Framing, roadmap, research brief  
- [x] Decision freeze (incl. D5 weights, D6 free NIM, D7 Obsidian artifacts)  
- [x] Artifact management pattern  
- [x] System map canvas  

### Not done yet

- [ ] Phase 1 literature matrix  
- [ ] Pin concrete free NIM coder model IDs  
- [ ] Phase 2 paper-organism prototype  

---

## In scope vs out of scope (early)

### In scope

- Sandboxed whitelist self-modification  
- Grid body + multi-seed fitness  
- Memory + small weight training + code mutation  
- Free NIM-assisted patches  
- SQLite + disk artifacts + vault run notes  
- Later: UI, small populations  

### Out of scope (for now)

- Paid-only LLM defaults  
- Open internet for organisms  
- Host self-deployment  
- Training a foundation model  
- Fancy 3D bodies before rewrite loop works  
- Production multi-tenant product  

---

## v0 defaults (frozen)

| Decision | Default |
|----------|---------|
| Body | Grid world (ALife-lite) |
| Fitness | Task-driven, multi-seed |
| Mutable code | Whitelist modules only |
| Learning | Memory + **trainable weights** + slow code mutation |
| LLM | NVIDIA NIM **free endpoints** only |
| Storage | SQLite + disk artifacts + **Obsidian lab notes** |
| Population | One active lineage |
| UI in Phase 2 | No — CLI + DB |
| Runtime / sandbox | Python · subprocess-first |

[[Open Decisions]] · [[Artifact Management]]

---

## Success looks like

**Phase 2:** holdout fitness of **Bcw** beats **B0** (and ablations show what carried the win), zero critical sandbox escapes.

**Longer term:** free multi-model pool, population dynamics, UI — without relaxing containment.

---

## Risks (short list)

| Risk | Mitigation |
|------|------------|
| Confusing weights vs code gains | Ablations B0/Bw/Bc/Bcw |
| Scope creep | [[Roadmap]] phase gates |
| Reward hacking | Frozen evaluator, holdout seeds |
| Host escape | Isolation + allowlist + no network |
| Free-tier RPM / model churn | Backoff; pin free model IDs; re-check catalog |
| Fake evolution demos | Require genome_id change + score Δ |

---

## Immediate next steps

1. Phase 1 survey from [[References]]  
2. Pin free coder model(s) on [build.nvidia.com/models](https://build.nvidia.com/models)  
3. Scaffold Phase 2 only after that  

---

## Meta

| Field | Value |
|-------|-------|
| Project | self-evolving-organism |
| Vault | `self-evolving-organism-docs` |
| Canvas | [[System Map]] |
| Stage | R&D · freeze locked |
| Updated | 2026-07-11 |
