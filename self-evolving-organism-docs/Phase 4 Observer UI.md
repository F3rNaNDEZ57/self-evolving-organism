---
tags: [phase/4, ui, observer, operator-console]
updated: 2026-07-11
---

# Phase 4 — Observer UI

## Goal

Make the experiment **legible** to a human operator — and **runnable** as an operator console. UI is **not** the organism brain: it inspects state and launches the same `seo` pipeline as the CLI.

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
| **Watch** | Grid episode replay — see the organism move on the food map |
| **Run** | Operator console — start mutate/evolve/ablate/weights/docker jobs |

## Run tab (operator console)

**Principle:** UI starts/monitors CLI subprocesses; science stays in `seo` kernel.

| Panel | Role |
|-------|------|
| Tabs (Mutate / Evolve / Ablate / Weights / Docker) | Form controls + Start |
| **Launch plan (current form)** | Live summary of form values + argv preview (what Start *would* run) |
| **Job status & log** | History of started jobs — select by job id |
| **Job parameters** | Flags, timing, paths for the selected job (open after exit) |
| **Final result + log** | Persisted snapshot after job ends |
| Live logs | Auto-refresh every 2s while running (`st.fragment`) |

### Defaults

- **Dry-run default**; live requires explicit confirm  
- **Single job at a time** (`artifacts/jobs/current.lock`)  
- Soft cancel = pause/freeze via Control; hard kill via **Kill job**  
- Windows jobs: `PYTHONUTF8` / `PYTHONIOENCODING=utf-8` + Rich `legacy_windows=False` (no cp1252 crashes on ε/δ)

### Delivery slices

| Slice | Deliverable | Status |
|-------|-------------|--------|
| **4.1** | Job runner + status/log files | ☑ `observer/jobs.py` |
| **4.2** | Run page: mutate, evolve, weights train | ☑ UI **Run** tab |
| **4.3** | Ablate + docker smoke + live confirm | ☑ |
| **4.4** | Job history in UI | ☑ list + log + kill + params |
| **Polish** | Live log · launch plan · final snapshot · Win encoding | ☑ merged `master` |

## Kill switch

`artifacts/control.json` fields:

- `mutations_paused` — soft pause
- `frozen` — hard stop
- `note` — operator message

Enforced by **`seo mutate`** and **`seo evolve`** (exit 3 if blocked). Does not stop in-flight Docker containers.

## Code map

| Path | Role |
|------|------|
| `src/organism/observer/app.py` | Streamlit app (Run + inspect surfaces) |
| `src/organism/observer/data.py` | Read-only SQLite/artifact queries |
| `src/organism/observer/control.py` | Pause/freeze state |
| `src/organism/observer/jobs.py` | CLI job subprocess manager + result snapshots |
| `src/organism/replay.py` | Host episode recording + RGB frames / GIF |
| `seo ui` | Launcher |
| `seo watch` | CLI: record episode → GIF under `artifacts/replays/` |

## Jobs on disk

| File | Content |
|------|---------|
| `artifacts/jobs/job_*.json` | Job metadata (status, pid, argv, times) |
| `artifacts/jobs/job_*.log` | Full stdout/stderr |
| `artifacts/jobs/job_*.result.json` | Final snapshot: params + log + CLI artifact |
| `artifacts/jobs/current.lock` | Single-job lock |

## Deliverables

- [x] Population / organism list
- [x] Lineage tree
- [x] Mutation inspector (scores, critic, cost, sources)
- [x] Event timeline
- [x] Kill switch / pause / freeze
- [x] Run from UI (operator console) — slices 4.1–4.4
- [x] Live log auto-refresh + launch plan + durable final result
- [x] Windows-safe job encoding for redirected CLI logs
- [x] Watch surface — grid episode replay + GIF (`seo watch`)
- [ ] Charts / multi-organism same-map view (Phase 5)

## See also

- [[Roadmap]]
- [[Home]]
- [[Working Rules]]
