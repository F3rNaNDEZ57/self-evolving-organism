---
title: Artifact Management
tags:
  - project/ops
  - phase/0
  - storage
aliases:
  - Artifacts
  - Lab notebook pattern
  - Runs
status: active
updated: 2026-07-11
---

# Artifact Management

> [!info]
> How **SQLite**, **disk artifacts**, and **this Obsidian vault** work together.
> Decision: [[Open Decisions#D7 — SQLite + artifacts + Obsidian (Changed)|D7]] · Canvas: [[System Map]] · Folders: [[Runs/README|Runs]] · [[Mutations/README|Mutations]] · [[Lineage/README|Lineage]]

---

## Three layers

```text
┌─────────────────────────────────────────────────────────┐
│  Obsidian vault (this folder)                            │
│  Human: run notes, lineage stories, decisions, charts    │
└──────────────────────────▲──────────────────────────────┘
                           │ links / optional export
┌──────────────────────────┴──────────────────────────────┐
│  artifacts/  (repo or data dir, not necessarily vault)   │
│  Machine: genome sources, weight ckpts, diffs, raw logs  │
└──────────────────────────▲──────────────────────────────┘
                           │ paths + ids
┌──────────────────────────┴──────────────────────────────┐
│  SQLite                                                  │
│  Machine: queryable lineage, fitness, events, LLM meta   │
└─────────────────────────────────────────────────────────┘
```

---

## SQLite (source of truth for metrics)

Tables (logical) stay as in [[Research Brief#Persistence model (v0)]]:

- genomes, evaluations, mutations, episodes, events, llm_calls  
- Plus: `weight_checkpoints` (id, genome_id, path, step, hash) when D5 training is on  

**Never** treat Obsidian as the only place fitness lives.

---

## Disk artifacts

Suggested layout (outside or beside vault; path configurable):

```text
artifacts/
  genomes/
    {genome_id}/
      policy.py · heuristics.py · memory_hooks.py
    active/ · seed/
  weights/
    w_<id>.npz                 # theta, baseline, feature_dim
    w_<id>.json                 # CheckpointMeta sidecar
    latest.json · best.json     # pointers
    index.jsonl                 # append-only registry
  mutations/
    m_<id>.json
  ablations/
    abl_<id>.json
  seo.sqlite                    # genomes, evals, mutations, weight_checkpoints
  active_genome.json
  last_ablation_report.json
  last_mutation_result.json
```

CLI: `seo weights train|list|show` · `seo eval --weights latest`

Genome **source** and **weights** are versioned separately: same code can have many weight checkpoints (lifetime learning).

---

## Obsidian vault (human lab notebook)

### What belongs here

| Content | Example note |
|---------|----------------|
| Experiment plans | `Runs/2026-07-11 pilot plan.md` |
| Run reports | `Runs/2026-07-12 b0-vs-bcw.md` |
| Mutation post-mortems | `Mutations/g-042 accepted.md` |
| Lineage narratives | `Lineage/seed-to-g-010.md` |
| Decision / design | [[Open Decisions]], [[Research Brief]] |

### Vault folders (created)

```text
self-evolving-organism-docs/
  System Map.canvas
  Home.md · Project Overview.md · …
  Runs/           # experiment write-ups  → [[Runs/README]]
  Mutations/      # optional per-mutation notes
  Lineage/        # optional story notes
  attachments/    # images, plots
```

### Run note frontmatter (template)

```yaml
---
title: Run 2026-07-12 B0 vs Bcw
tags:
  - run
  - phase/2
run_id: run_2026_07_12_a
baseline: Bcw
genome_id: g_010
parent_genome_id: g_009
fitness: 12.4
holdout_fitness: 11.1
nim_model: deepseek-v4-flash
artifact_path: artifacts/genomes/g_010
weights_path: artifacts/weights/g_010/best.pt
sqlite: path/to/experiment.db
status: complete
---
```

Body of the note: hypothesis, config summary, charts, what you learned, links to parent/child notes.

### Mutation note (optional)

Link `mutation_id`, decision (accept/reject), short human summary of the diff, whether weights were warm-started from parent.

---

## Write path (runtime)

1. Evaluate candidate → write **SQLite** rows  
2. On accept → write **artifact** snapshot (code + optional weight init)  
3. Optionally append/export a **Runs/** or **Mutations/** markdown stub into the vault  

Step 3 can be:

- manual (you write the note), or  
- a small exporter script (Phase 2+) that only writes markdown + frontmatter (no binary blobs into the vault)

---

## What not to do

- Do not dump full step-level telemetry into Obsidian notes  
- Do not commit API keys into the vault  
- Do not make Obsidian the only backup of genomes  
- Do not store large `.pt` files inside the vault if they bloat sync; **link paths** instead  

---

## Sync with git

| Path | Git? |
|------|------|
| Vault notes (this docs vault) | Yes (research memory) |
| SQLite DB | Optional / gitignore large DBs; export summaries |
| `artifacts/genomes` text | Yes if small; or release packs |
| Weight binaries | Usually gitignore; keep hashes in SQLite |

---

## See also

[[System Map]] · [[Open Decisions]] · [[Research Brief]] · [[Project Overview]] · [[Home]] · [[Runs/README|Runs]]
