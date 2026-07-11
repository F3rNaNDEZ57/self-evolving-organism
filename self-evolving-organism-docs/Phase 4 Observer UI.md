---
tags: [phase/4, ui, observer]
updated: 2026-07-11
branch: feat/phase4-observer-ui
---

# Phase 4 — Observer UI

## Goal

Make the experiment **legible** to a human operator without reading raw SQLite dumps. UI is **read-mostly** — not the organism brain.

## Launch

```powershell
cd C:\Projects\self-evolving-organism
.\.venv\Scripts\Activate.ps1
pip install -e ".[ui]"
seo ui
# http://localhost:8501
```

## Surfaces

| Surface | What |
|---------|------|
| **Overview** | Active genome, last ablation δ, pool metrics |
| **Genomes** | Population table + source viewer |
| **Lineage** | Parent→child tree + edges |
| **Mutations** | Inspector: decision, fitness, critic, tokens, sources |
| **Timeline** | Event log (filterable) |
| **Evaluations** | Fitness history table |
| **Control** | Pause / freeze mutations → `artifacts/control.json` |

## Kill switch

`artifacts/control.json` fields:

- `mutations_paused` — soft pause
- `frozen` — hard stop
- `note` — operator message

Enforced by **`seo mutate`** and **`seo evolve`** (exit 3 if blocked). Does not stop in-flight Docker containers.

## Code map

| Path | Role |
|------|------|
| `src/organism/observer/app.py` | Streamlit app |
| `src/organism/observer/data.py` | Read-only SQLite/artifact queries |
| `src/organism/observer/control.py` | Pause/freeze state |
| `seo ui` | Launcher |

## Deliverables

- [x] Population / organism list
- [x] Lineage tree
- [x] Mutation inspector (scores, critic, cost, sources)
- [x] Event timeline
- [x] Kill switch / pause / freeze
- [ ] Polish: live auto-refresh, charts, multi-organism (Phase 5)

## See also

- [[Roadmap]]
- [[Home]]
- [[Working Rules]]
