---
title: Glossary
tags:
  - reference
  - glossary
aliases:
  - Definitions
  - Vocabulary
  - Terms
status: active
updated: 2026-07-11
---

# Glossary

> [!info]
> Shared vocabulary for [[Project Overview|self-evolving-organism]]. Prefer these terms in notes and code comments.
>
> Hub: [[Home]] · Canvas: [[System Map]] · Design: [[Research Brief]] · Plan: [[Roadmap]]

---

## Organism

A sandboxed agent with a versioned **genome**, a **body** in the world, structured **memory**, **trainable weights**, and a **lineage identity**. May *request* mutations; only the **kernel** applies them after evaluation.

→ [[Research Brief#Conceptual model]] · [[Project Overview#What an organism is]] · [[System Map]]

---

## Genome

Mutable source modules that define behavior (policy, heuristics, optional memory hooks). Versioned; parent/child links form the lineage.

**v0 mutable:** `policy` / `heuristics` / `memory_hooks` (whitelist).  
**Not mutable:** interface contracts, kernel.

---

## Body

Embodiment in the environment: position, energy, sensors, actuators, budgets, alive/dead status.

**v0:** simulated grid-world body (not a host OS process with open tools).

---

## Kernel

Immutable experimental harness: world simulator, sandbox, evaluator, LLM client, persistence, operator controls.

> [!warning]
> Organisms must never be able to edit the kernel.

---

## Experience

Structured record of interaction used for learning and mutation context — not only raw token dumps.

Typical layers: event log · episode summary · distilled lessons · mutation memory.

→ [[Research Brief#Experience and memory]]

---

## Weights (phenotype)

Small trainable parameters updated during an organism's lifetime (fast learning). Separate from genome code (slow evolution).

**Checkpoints (Phase 2):** `artifacts/weights/w_*.npz` + sidecar JSON, SQLite `weight_checkpoints`, pointers `latest.json` / `best.json`. CLI: `seo weights train|list|show`.

→ [[Open Decisions#D5 — Memory + weight training (Changed)|D5]] · [[Artifact Management]] · [[Phase 2 Scaffold]]

---

## Memory

Organism-local store of experience and optional distilled lessons. Data is mutable; it is **not** a backdoor into kernel code.

---

## Mutation

A proposed change to whitelist genome modules (usually LLM-authored), applied only after static checks and sandbox evaluation under the mutation protocol.

→ [[Research Brief#Mutation protocol]]

---

## Fitness

Scalar (or vector) score computed **only** by the frozen evaluator over one or more episodes/seeds. Genome code cannot redefine the fitness function.

→ [[Research Brief#Fitness and evaluation]]

---

## Lineage

Parent/child chain of genomes (and optionally organisms). Every accepted mutation extends lineage with metrics and cost metadata.

---

## Archive

Stored library of variants and evaluations — parents, rejected candidates, elites — used for analysis and later open-ended search (DGM-style archive ideas: [[References]]).

---

## LLM pool

External multi-model assistance layer on **NVIDIA NIM free endpoints**: coder, **critic** (Phase 3), summarizer, router. **Not** the organism itself. Default configs must not require paid-only models. Critic = static AST precheck + free NIM JSON approve/reject before Docker eval.

→ [[Research Brief#LLM pool (NVIDIA NIM)]] · [[Open Decisions#D6 — Free NVIDIA NIM models (Changed)|D6]] · [[References#NVIDIA NIM]]

---

## Sandbox

Isolated execution environment for genome code: import allowlist, FS jail, no network, resource limits, timeouts.

---

## Behavioral loop

Fast loop: sense → act → reward → update memory, body, and **weights**. Does not require code changes.

---

## Genomic loop

Slow loop: trigger → propose patch → check → evaluate → accept/reject → archive. This is where “evolution” is claimed.

---

## Breeder mode

Human-defined fitness and controlled reproduction/mutation rates — as opposed to an open ecosystem where selection emerges without operator-defined goals.

Early phases prefer breeder mode for safety and science.

---

## Paper organism

Minimal Phase 2 prototype: one lineage, toy world, single LLM mutation path, CLI/DB observability — enough to test whether fitness can rise under sandboxed rewrite.

→ [[Roadmap#Phase 2 — Paper organism]]

---

## Evaluator

Frozen kernel component that scores genomes on seeded episodes. Must be independent of organism-writable code.

---

## Policy

Genome-implemented mapping from observations to actions (`act`). Primary mutation target in v0.

---

## Holdout seeds

Evaluation seeds not used during mutation selection, used to detect overfitting to the training seed set.

---

## See also

[[Home]] · [[System Map]] · [[Project Overview]] · [[Research Brief]] · [[Roadmap]] · [[Open Decisions]] · [[Artifact Management]] · [[References]]
