---
tags: [phase/4, ui, observer, operator-console]
updated: 2026-07-11
---

# Phase 4 — Observer UI

## Goal

Make the experiment **legible** to a human operator — and next, **runnable** as an operator console. UI is **not** the organism brain: it inspects state and launches the same `seo` pipeline as the CLI.

## Launch

```powershell
cd C:\Projects\self-evolving-organism
.\.venv\Scripts\Activate.ps1
pip install -e ".[ui]"
seo ui
# http://localhost:8501
```

## Surfaces (v1 — live)

| Surface | What |
|---------|------|
| **Overview** | Active genome, last ablation δ, pool metrics |
| **Genomes** | Population table + source viewer |
| **Lineage** | Parent→child tree + edges |
| **Mutations** | Inspector: decision, fitness, critic, tokens, sources |
| **Timeline** | Event log (filterable) |
| **Evaluations** | Fitness history table |
| **Control** | Pause / freeze mutations → `artifacts/control.json` |
| **Run** | Operator console — start mutate/evolve/ablate/weights/docker jobs |

## Kill switch

`artifacts/control.json` fields:

- `mutations_paused` — soft pause
- `frozen` — hard stop
- `note` — operator message

Enforced by **`seo mutate`** and **`seo evolve`** (exit 3 if blocked). Does not stop in-flight Docker containers.

## Planned: Run from UI (operator console)

**Decision (2026-07-11):** extend Phase 4 so the operator can **start jobs from the UI**, without embedding science logic in Streamlit.

### Principle

| Layer | Role |
|-------|------|
| UI | Buttons, params, logs, confirm live actions |
| Job runner | Subprocess `seo …`, status + log files under `artifacts/jobs/` |
| Kernel / CLI | Unchanged source of truth (mutate, evolve, ablate, weights) |

### Defaults

- **Dry-run default**; live requires explicit confirm  
- **Single job at a time** (lock while running)  
- Soft cancel = pause/freeze; hard kill process = later  
- Long jobs (ablate) stream logs; UI polls status  

### Delivery slices

| Slice | Deliverable | Status |
|-------|-------------|--------|
| **4.1** | Job runner + status/log files | ☑ `observer/jobs.py` |
| **4.2** | Run page: mutate, evolve, weights train | ☑ UI **Run** tab |
| **4.3** | Ablate + docker smoke + live confirm | ☑ |
| **4.4** | Job history in UI | ☑ job list + log tail + kill |

## Code map

| Path | Role |
|------|------|
| `src/organism/observer/app.py` | Streamlit app |
| `src/organism/observer/data.py` | Read-only SQLite/artifact queries |
| `src/organism/observer/control.py` | Pause/freeze state |
| `src/organism/observer/jobs.py` | CLI job subprocess manager |
| `seo ui` | Launcher |

## Jobs on disk

`artifacts/jobs/job_*.json` · `job_*.log` · `current.lock`

## Deliverables

- [x] Population / organism list
- [x] Lineage tree
- [x] Mutation inspector (scores, critic, cost, sources)
- [x] Event timeline
- [x] Kill switch / pause / freeze
- [x] Run from UI (operator console) — slices 4.1–4.4
- [ ] Polish: auto-refresh, charts, multi-organism (Phase 5)

## See also

- [[Roadmap]]
- [[Home]]
- [[Working Rules]]
