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
| Indexed | 2026-07-11 |
| Commit | `69befed` (up-to-date) |
| Symbols / nodes | 1,013 |
| Edges | 1,638 |
| Clusters | 14 |
| Flows / processes | 82 |
| Status | ✅ up-to-date |

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
