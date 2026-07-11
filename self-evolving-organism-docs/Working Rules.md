---
title: Working Rules
tags:
  - meta
  - process
  - dashboard
aliases:
  - Vault rules
  - After every task
  - Agent rules
status: active
updated: 2026-07-11
---

# Working Rules

> [!warning] Standing process rule
> **After every completed task**, update this vault **and** the dashboard canvas.
>
> Machine-facing copy: repo-root `AGENTS.md`

---

## Rule 1 — Vault + canvas after every task

When a task finishes (research, code, config, experiment, decision):

| Step | Action |
|------|--------|
| 1 | Update relevant notes (status, checklists, new findings) |
| 2 | Update **[[System Map]]** (phase, next action, verified infra) |
| 3 | Ensure **[[Home]]** still points at current reality |
| 4 | Never store API keys here — only in `.env` |

### Done means

- [ ] Task deliverable itself complete  
- [ ] Vault truthful  
- [ ] Canvas dashboard truthful  
- [ ] No secrets in git/vault  

### Tiny tasks

If project **state** changed → still update vault/canvas.  
If pure no-op polish → canvas optional.

---

## Rule 2 — Canvas is the dashboard

**[[System Map]]** is the project dashboard, not a one-off diagram.

Keep current:

- Phase 0 / 1 / 2… status  
- **Next action** block  
- Live pins / Docker / freezes  
- **Roadmap checklist cards** (☑ / ☐ per phase deliverable)  
- Clean layout (readable, no overlaps)  

### Rule 2b — Canvas layout contract (do not mess up)

When editing `System Map.canvas`, **preserve this shape**. Update **text content** inside cards; do not collapse sections into a dump or restack nodes on top of each other.

#### Fixed vertical sections (top → bottom)

| # | Section | Contents |
|---|---------|----------|
| 0 | Header strip | Title · process rule · verified status (full-width bars) |
| 1 | Vault notes | File cards linking notes (2 rows max) |
| 2 | **Roadmap checklists** | Four phase cards: 0–1 · 2 · 3 · 4–6 with ☑/☐ items |
| 3 | Next + CLI | Next actions card · CLI card side-by-side |
| 4–6 | Three columns | Organism (mutable) · Kernel (frozen) · Live science |
| 7–8 | Bottom row | Two timescales · Storage (D7) |

#### Spacing (minimums)

| Rule | Value |
|------|------:|
| Canvas usable width | ~2800 px |
| Gap between major **groups** | ≥ **80** px vertical |
| Gap between sibling **cards** | ≥ **40** px |
| Gap inside group (padding) | ≥ **50** px from group edge to first child |
| File tiles | ≥ **280×90** · horizontal gap ≥ **30** |
| Text cards (roadmap) | ≥ **600** wide · ≥ **500** tall for full phase lists |
| Body / status lines | height enough that **no text clips** (prefer extra height over dense packing) |

#### Content rules

1. **Unicode checkboxes only** in canvas text: `☑` done · `☐` open — **not** markdown `- [x]` (Obsidian canvas often does not render task lists).
2. **Prefer edit-in-place**: change the wording of existing cards; add a new card only if a new durable concern appears, then place it in the correct section with spacing rules above.
3. **Do not** shrink cards to “fit everything on one screen” — zoom/scroll is OK; overlap is not.
4. **Edges** only between related architecture nodes (body↔world, genome↔sandbox, mut↔genome, memory→mut, etc.). Avoid long edges that cross checklist or file sections.
5. After any canvas edit: open in Obsidian, **fit view**, confirm no overlaps and all text visible; then commit.

#### Forbidden

- Stacking nodes with overlapping bounding boxes  
- Cramming phase checklists into a single tiny “Phases OK/TODO” blurb  
- Deleting the four roadmap checklist cards without replacing them with an equal layout  
- Dumping full report tables into small boxes (link to Runs/ notes instead)

---

## Rule 3 — Honor the freeze

See [[Open Decisions]]. Do not reopen D1–D12 without an explicit owner decision and amendment log entry.

---

## Rule 4 — Free NIM + Docker

- Default models: free NIM only → [[NIM Pin Log]]  
- Organism runtime: Docker `--network none` (Phase 1 verified)  

---

## Rule 5 — GitNexus

- Repo is indexed — see [[GitNexus]]  
- After major code changes: `npx gitnexus analyze`  
- Prefer impact/query tools before large refactors (see `AGENTS.md` gitnexus block)  

---

## See also

[[Home]] · [[System Map]] · [[GitNexus]] · [[Open Decisions]] · [[Phase 1 Research Package]] · repo `AGENTS.md`
