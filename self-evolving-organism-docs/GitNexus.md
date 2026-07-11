---
title: GitNexus
tags:
  - tooling
  - gitnexus
  - meta
aliases:
  - Code intelligence
  - Index
status: active
updated: 2026-07-11
---

# GitNexus

> [!success] Indexed
> Repo registered as **self-evolving-organism**.
>
> Dashboard: [[System Map]] · Rules: [[Working Rules]] · `AGENTS.md` (gitnexus section appended)

---

## Index stats (initial)

| Metric | Value |
|--------|------:|
| Indexed | 2026-07-11 (refreshed after origin history) |
| Commit | `92b869b` then re-analyze post-evolve work |
| Symbols / nodes | **1,132** |
| Edges | **1,873** |
| Clusters | 15 |
| Flows / processes | **97** |
| Status | ✅ up-to-date at analyze time |

---

## Commands

```powershell
cd C:\Projects\self-evolving-organism
npx gitnexus analyze          # build / refresh index
npx gitnexus status           # freshness
npx gitnexus list             # all indexed repos
npx gitnexus wiki             # optional LLM wiki (needs API key)
npx gitnexus clean --force    # delete index
```

Index lives in **`.gitnexus/`** (gitignored). Re-run `analyze` after major code changes.

---

## Agent contract

GitNexus appends a block to repo-root `AGENTS.md`:

- Impact analysis before editing symbols  
- `detect_changes` before commits  
- Prefer graph query over blind grep  

Our vault/canvas process rule remains **above** that block.

---

## See also

[[Home]] · [[Working Rules]] · [[Phase 2 Scaffold]]
