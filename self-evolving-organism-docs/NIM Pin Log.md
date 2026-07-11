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
updated: 2026-07-11
---

# NIM Pin Log

> [!success] Verified live
> `GET /v1/models` + chat smoke + Docker smoke completed **2026-07-11**.
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

## Pinned model IDs (exact API strings)

| Role | `model` id | Chat smoke |
|------|------------|------------|
| **Coder primary** | `deepseek-ai/deepseek-v4-flash` | OK |
| **Coder fallback** | `nvidia/nemotron-3-nano-30b-a3b` | OK |
| **Critic** | `nvidia/nemotron-3-nano-30b-a3b` | OK |
| **Summarizer** | `meta/llama-3.1-8b-instruct` | OK |

### Confirmed present (alternates)

| Role | IDs on this account |
|------|---------------------|
| Coder alts | `z-ai/glm-5.2`, `minimaxai/minimax-m2.7`, `mistralai/mistral-nemotron`, `deepseek-ai/deepseek-v4-pro` |
| Critic alts | `openai/gpt-oss-20b`, `meta/llama-3.1-8b-instruct` |
| Summarizer alts | `google/gemma-2-2b-it`, `meta/llama-3.2-3b-instruct` |

### Prior short-name → verified id

| Prior note | Verified API id |
|------------|-----------------|
| `deepseek-v4-flash` | `deepseek-ai/deepseek-v4-flash` |
| `nemotron-3-nano-30b-a3b` | `nvidia/nemotron-3-nano-30b-a3b` |
| `llama-3.1-8b-instruct` | `meta/llama-3.1-8b-instruct` |
| `gpt-oss-20b` | `openai/gpt-oss-20b` |
| `glm-5.2` | `z-ai/glm-5.2` |
| `minimax-m2.7` | `minimaxai/minimax-m2.7` |
| `mistral-nemotron` | `mistralai/mistral-nemotron` |
| `gemma-2-2b-it` | `google/gemma-2-2b-it` |

Repo machine config (no secrets): `config/nim.pinned.yaml`

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

---

## Security notes

> [!danger] API key hygiene
> - Key lives only in repo-root **`.env`** (listed in `.gitignore`).
> - **Never** paste keys into Obsidian notes, git commits, or chat if avoidable.
> - If this key was shared in chat/logs, **rotate it** at [build.nvidia.com](https://build.nvidia.com/settings/api-keys) after pinning.

---

## See also

[[Phase 1 Research Package]] · [[Open Decisions]] · [[Home]] · [[Artifact Management]]
