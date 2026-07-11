---
title: NIM Pin Log
tags:
  - phase/1
  - nim
  - ops
aliases:
  - Model pins
  - Free NIM ids
status: verified
updated: 2026-07-12
---

# NIM Pin Log

> [!success] Verified live
> `GET /v1/models` + chat smoke **2026-07-12** (121 models). Pins upgraded for coding quality.
>
> Full package: [[Phase 1 Research Package]] · Secrets: repo-root `.env` (gitignored)

---

## API access

| Field | Value |
|-------|--------|
| Base URL | `https://integrate.api.nvidia.com/v1` |
| Auth | `NVIDIA_API_KEY` in **`.env`** (not in vault) |
| Models returned | **121** |
| Free-tier RPM | Design for **40** (account-level; see Phase 1 package) |

---

## Pinned model IDs (exact API strings) — 2026-07-12 R&D

| Role | `model` id | Chat smoke | Notes |
|------|------------|------------|-------|
| **Coder primary** | `z-ai/glm-5.2` | OK ~3.5s | Agentic/coding free endpoint |
| **Coder fallback** | `deepseek-ai/deepseek-v4-pro` | OK ~37s | Parse/quality retry (slower, stronger) |
| **Critic** | `openai/gpt-oss-120b` | OK ~1s | Stronger schema/safety |
| **Summarizer** | `meta/llama-3.1-8b-instruct` | OK | Cheap distill |

### Previous pins (still available)

| Role | Prior id |
|------|----------|
| Coder | `deepseek-ai/deepseek-v4-flash` |
| Critic/fallback | `nvidia/nemotron-3-nano-30b-a3b` |

### Confirmed present (alternates)

| Role | IDs on this account |
|------|---------------------|
| Coder alts | `deepseek-v4-flash`, `deepseek-v4-pro`, `minimax-m3`, `minimax-m2.7`, `mistral-nemotron`, `gpt-oss-120b` |
| Critic alts | `gpt-oss-20b`, `nemotron-3-nano-30b-a3b`, `llama-3.1-8b-instruct` |
| Summarizer alts | `gemma-2-2b-it`, `llama-3.2-3b-instruct` |
| Failed smoke | `moonshotai/kimi-k2.6` (404 for this account) |

### Prior short-name → verified id

| Prior note | Verified API id |
|------------|-----------------|
| `deepseek-v4-flash` | `deepseek-ai/deepseek-v4-flash` |
| `deepseek-v4-pro` | `deepseek-ai/deepseek-v4-pro` |
| `nemotron-3-nano-30b-a3b` | `nvidia/nemotron-3-nano-30b-a3b` |
| `llama-3.1-8b-instruct` | `meta/llama-3.1-8b-instruct` |
| `gpt-oss-20b` | `openai/gpt-oss-20b` |
| `gpt-oss-120b` | `openai/gpt-oss-120b` |
| `glm-5.2` | `z-ai/glm-5.2` |
| `minimax-m2.7` | `minimaxai/minimax-m2.7` |
| `minimax-m3` | `minimaxai/minimax-m3` |
| `mistral-nemotron` | `mistralai/mistral-nemotron` |

Repo machine config (no secrets): `config/nim.pinned.yaml`

---

## Mutation self-improvement history (2026-07-12)

Coder/critic prompts inject **SQLite mutation memory**:

- Recent **accepts** with fitness Δ (what worked)
- Same-parent + global **rejects** (what failed)
- DIVERSITY themes (food-tweak ban, forbidden Observation fields, empty-body ban)

Code: `src/organism/mutation_memory.py` · used by `propose_policy_patch` with `k=12`.

---

## Docker smoke test

| Item | Result |
|------|--------|
| Docker Desktop | **OK** — Engine 28.5.1, context `desktop-linux` |
| Image | `python:3.12-slim` (pulled) |
| Flags | `--rm --network none --memory 512m --cpus 1` |
| Python | `python_ok` |
| Network | **`network_blocked`** (`OSError` on connect to 1.1.1.1:53) |
| Overall | **`smoke_pass`** |

Matches Phase 1 recommendation: container jail with no network.
