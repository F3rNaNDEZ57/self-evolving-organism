# Agent & contributor rules — self-evolving-organism

These rules apply to **every** AI agent and human contributor working in this repository.

## Standing rule: vault + canvas after every task

**After each and every completed task** (feature, research note, config change, bugfix, decision, experiment, docs edit — anything that changes project state):

1. **Update the Obsidian vault** in `self-evolving-organism-docs/`
   - Correct status, checklists, decisions, and links
   - Add or amend notes when new artifacts appear (runs, pins, ADRs, etc.)
   - Never put secrets (API keys) in the vault — use `.env` only

2. **Update the project dashboard canvas**
   - File: `self-evolving-organism-docs/System Map.canvas`
   - Keep status banner, phase checklist, “next action”, and verified infra accurate
   - Prefer a clean layout (no overlaps); fit the canvas as a **dashboard**, not a dump

3. **Cross-link**
   - New notes should appear from `Home.md` (and Phase notes when relevant)
   - Do not leave the canvas or Home pointing at obsolete “next steps”

### Definition of done (task-level)

A task is **not done** until:

- [ ] Code/config/docs for the task itself are complete  
- [ ] Vault notes reflect the new truth  
- [ ] `System Map.canvas` reflects phase, status, and next action  
- [ ] No secrets committed (`.env` stays gitignored)  

### When the task is tiny

Even one-line fixes: still bump vault status **if** project state changed (e.g. phase complete, new pin, failed smoke test).  
If truly no state change (typo-only in non-vault code comment), skip canvas but prefer a one-line Home “last updated” only when useful.

## Other standing rules (project freeze)

- Honor Phase 0 decisions in `self-evolving-organism-docs/Open Decisions.md` unless the owner explicitly reopens them.
- Free NVIDIA NIM endpoints only for default models; pins in `config/nim.pinned.yaml` + `.env`.
- Organism code runs in Docker (`--network none`); never weaken that without an explicit decision.
- Phase 2 = paper organism + ablations B0/Bw/Bc/Bcw; no full UI yet.

## Where the human dashboard lives

| Artifact | Path |
|----------|------|
| Vault root | `self-evolving-organism-docs/` |
| Dashboard canvas | `self-evolving-organism-docs/System Map.canvas` |
| Hub note | `self-evolving-organism-docs/Home.md` |
| Working rules (vault copy) | `self-evolving-organism-docs/Working Rules.md` |

---

*This file is the machine-facing contract. Keep it short; put narrative in the vault.*

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **self-evolving-organism** (1338 symbols, 2266 relationships, 117 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/self-evolving-organism/context` | Codebase overview, check index freshness |
| `gitnexus://repo/self-evolving-organism/clusters` | All functional areas |
| `gitnexus://repo/self-evolving-organism/processes` | All execution flows |
| `gitnexus://repo/self-evolving-organism/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
