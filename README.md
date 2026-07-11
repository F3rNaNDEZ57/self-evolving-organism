# self-evolving-organism

[![GitHub](https://img.shields.io/badge/github-F3rNaNDEZ57%2Fself-evolving-organism-blue)](https://github.com/F3rNaNDEZ57/self-evolving-organism)

Phase 2 **paper organism**: simulated grid body, lifetime weight learning, sandboxed genome mutation via **free NVIDIA NIM**, lineage in SQLite + artifacts.

**Remote:** `https://github.com/F3rNaNDEZ57/self-evolving-organism.git`  
Research vault / dashboard: `self-evolving-organism-docs/` (open **System Map** canvas).

## Status

| Phase | Status |
|-------|--------|
| 0 Concept freeze | Done |
| 1 Research + NIM pin + Docker | Done |
| **2 Paper organism** | **Scaffolding** |
| 3–6 | Later |

## Setup

```powershell
cd C:\Projects\self-evolving-organism
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# Ensure .env has NVIDIA_API_KEY (see .env.example)
# Docker Desktop required for sandboxed genome runs
```

## CLI

```powershell
# Run one evaluation (B0 by default)
seo eval --ablation B0

# Bw = weights on
seo eval --ablation Bw

# Episode demo (print summary)
seo demo --seed 0

# Init DB + copy seed genome to artifacts
seo init

# Show pinned NIM models
seo pins

# Mutation loop (dry-run offline, or live free NIM)
# Default: static + free NIM critic before Docker eval
seo mutate --dry-run --ablation Bc
seo mutate --ablation Bc
seo mutate --no-critic --dry-run

# Full ablation suite + holdout δ (Bcw − B0)
seo ablate --quick
seo ablate --live --max-mutations 3

# Weight checkpoints (phenotype)
seo weights train --passes 2
seo weights list
seo weights show latest
seo eval --ablation Bw --weights latest

# Continuous evolution (schedule + plateau triggers)
seo evolve --cycles 5 --dry-run --every 8 --plateau 20 --max-mutations 5
seo evolve --cycles 10 --live --ablation Bc

# Docker episode isolation
seo docker-build
seo docker-smoke
seo docker-eval --seeds 0,1
seo eval --docker --ablation Bc
seo eval --host --ablation B0
```

## Layout

```text
src/organism/     # kernel + runtime (frozen harness)
genomes/seed/     # initial whitelist genome modules
config/           # pre-reg + NIM pins
artifacts/        # runtime DB, genomes, weights (gitignored)
self-evolving-organism-docs/  # Obsidian vault + System Map dashboard
```

## Rules

After every task: update vault + `System Map.canvas` (see `AGENTS.md`).

## Safety

Organism code is intended to run under Docker `--network none`. Do not point the sandbox at host Python for untrusted LLM patches.
