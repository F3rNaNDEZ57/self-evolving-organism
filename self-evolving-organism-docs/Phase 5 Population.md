---
tags: [phase/5, population, elites]
updated: 2026-07-11
---

# Phase 5 — Population dynamics (scaffold)

## Goal

Move from **single active lineage** toward an operator-curated **elite archive** and explicit **parent selection** for mutations. UI/CLI remain the operator console — not the organism brain.

## Delivered (scaffold)

| Item | Status |
|------|--------|
| Elite registry `artifacts/elites/registry.json` | ☑ |
| `seo elite list \| promote \| demote` | ☑ |
| Genomes UI: promote / demote + elite table | ☑ |
| Mutate parent picker (active · elite · genome) | ☑ |
| `seo mutate --parent-id <id>` resolves path correctly | ☑ |
| Job runner passes `--parent-id` | ☑ |

## Not yet (later Phase 5)

- [ ] Automatic selection policy (tournament / fitness rank)
- [ ] Multi-organism budgets / concurrent lineages
- [ ] Multi-agent same-map Watch
- [ ] Solo vs population experiment write-up

## Operator flow

```powershell
# Promote a strong genome
seo elite promote g_xxxxxxxx --note "holdout champ"

# Mutate from that elite (not only active)
seo mutate --dry-run --ablation Bc --parent-id g_xxxxxxxx

# Or: seo ui → Genomes (promote) → Run → Mutate → Parent genome
```

## Code map

| Path | Role |
|------|------|
| `src/organism/elites.py` | Registry promote/demote/list/resolve |
| `src/organism/mutation.py` | `resolve_parent_genome(..., parent_id=)` |
| `src/organism/cli.py` | `seo elite *` |
| `src/organism/observer/app.py` | Genomes + Run parent picker |
| `src/organism/observer/jobs.py` | `build_mutate_argv(parent_id=)` |

## Design notes

- Elites are **references** to existing genome dirs (no duplicate brain).
- Promoting does **not** rewrite `active_genome.json`.
- Accept still promotes via the normal mutation accept path.
- Registry is the elite source of truth; SQLite status may be tagged `elite` when not `active`.

## See also

- [[Roadmap]]
- [[Phase 4 Observer UI]]
- [[Home]]
