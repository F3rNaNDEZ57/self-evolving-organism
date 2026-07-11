---
title: References
tags:
  - reference
  - bibliography
  - phase/1
aliases:
  - Bibliography
  - Sources
  - Reading list
status: active
updated: 2026-07-11
---

# References

> [!info]
> Seed reading list for Phase 1 survey. Expand with notes and takeaways as you go.
>
> Related: [[Roadmap#Phase 1 — Literature & systems survey]] · [[Research Brief]] · [[System Map]] · [[Home]]

---

## Self-improving / self-rewriting agents

### Darwin Gödel Machine (Sakana AI)

- **Landing:** [sakana.ai/dgm](https://sakana.ai/dgm/)
- **Paper:** [arXiv:2505.22954](https://arxiv.org/abs/2505.22954) — *Darwin Godel Machine: Open-Ended Evolution of Self-Improving Agents*
- **Why it matters:** Empirical self-rewrite of coding agents; archive of variants; sandbox + oversight; closest modern cousin to our genomic loop.

> [!todo] Phase 1 notes
> - [ ] 3–5 takeaways  
> - [ ] What to steal (archive, eval protocol, safety)  
> - [ ] What not to copy (scope, body model)  

---

## Artificial life / digital organisms

### Avida

- **Overview:** [Avida digital evolution platform](https://alife.org/encyclopedia/digital-evolution/avida/)
- **Why it matters:** Classic digital organisms with bodies/resources on a lattice; selection and evolution of programs — embodiment metaphors for our grid body.

> [!todo] Phase 1 notes
> - [ ] 3–5 takeaways  
> - [ ] Mapping Avida concepts → our organism schema  

---

## Inference / agent infrastructure

### NVIDIA NIM

- **Developer hub:** [developer.nvidia.com/nim](https://developer.nvidia.com/nim)
- **API catalog (free endpoints):** [build.nvidia.com/models](https://build.nvidia.com/models) · [build.nvidia.com](https://build.nvidia.com/)
- **Why it matters:** Target LLM pool backend; **free endpoints only** for v0 defaults (D6); OpenAI-compatible patterns; multi-model routing for coder/critic/summarizer.

> [!todo] Phase 1 notes
> - [ ] API auth / base URL patterns we will use  
> - [ ] Candidate models for coder vs critic  
> - [ ] Cost/latency notes  

---

## Safety / evolvable AI

### Evolvable AI discussion (PNAS-linked framing)

- **Article:** [Evolvable AI: Threats of a new major transition in evolution](https://www.pnas.org/doi/10.1073/pnas.2527700123)
- **Why it matters:** Breeder vs ecosystem modes; sandboxing; replication gates — language for our containment stance.

> [!todo] Phase 1 notes
> - [ ] Controls we must implement in Phase 2  
> - [ ] What we explicitly defer (open ecosystem)  

---

## Classical / conceptual background

| Topic | Pointer | Use |
|-------|---------|-----|
| Gödel machine (Schmidhuber) | Search: *Gödel machines self-improving* | Theoretical ancestor; we use empirical, not proof-based, improvement |
| Open-endedness | Clune et al. / open-ended evolution surveys | Framing for archive + diversity later |
| Digital evolution | ALife literature beyond Avida | Population dynamics Phase 5 |

*(Add concrete links as you pin preferred editions.)*

---

## Internal project docs

| Note | Role |
|------|------|
| [[Home]] | Vault hub |
| [[System Map]] | Architecture canvas |
| [[Project Overview]] | Orientation |
| [[Roadmap]] | Phases |
| [[Research Brief]] | v0 freeze detail |
| [[Open Decisions]] | Locked D1–D12 |
| [[Artifact Management]] | SQLite + disk + Obsidian |
| [[Glossary]] | Terms |
| [[Phase 1 Research Package]] | NIM pins, matrix, containment, pre-reg |

---

## Comparison matrix (placeholder)

> [!example] Fill in Phase 1
> Copy rows as you survey systems.

| System | Self-rewrite? | Body? | Archive? | Sandbox? | Steal | Ignore |
|--------|---------------|-------|----------|----------|-------|--------|
| DGM | Yes | Weak / coding agent | Yes | Yes | | |
| Avida | Evolves programs | Yes (lattice) | Pop. | Lab | | |
| Our v0 target | Yes (LLM+eval) | Grid sim | Lineage | Required | — | — |

---

## How to add a reference

1. New `###` heading or row in a table  
2. Link + **why it matters** (1–2 sentences)  
3. Optional callout with takeaways  
4. Wikilink from [[Research Brief]] or experiment notes when you use an idea  
