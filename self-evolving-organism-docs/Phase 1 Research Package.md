---
title: Phase 1 Research Package
tags:
  - phase/1
  - research
  - status/active
aliases:
  - Phase 1
  - NIM pin
  - Literature matrix
  - Containment
  - Pre-registration
status: active
updated: 2026-07-11
---

# Phase 1 Research Package

> [!info]
> Research and verification only. Architecture and Phase 0 freeze are **accepted as given** ([[Open Decisions]], [[Research Brief]], [[System Map]]).
>
> **Survey date:** 2026-07-11 · **Host:** Windows 11 · **Stack:** Python

---

## 1. NIM free-endpoint model pinning

### 1.1 Method and limits

| Item | Detail |
|------|--------|
| Catalog browsed | [build.nvidia.com/models](https://build.nvidia.com/models) (live list; page 1 of ~144 models) |
| Base URL (frozen) | `https://integrate.api.nvidia.com/v1` |
| Auth | `nvapi-…` from [build.nvidia.com](https://build.nvidia.com/) |
| Free-status method | UI badges on catalog/model pages (“Free Endpoint” / “Downloadable Free Endpoint”) + secondary reports |
| **Cannot fully verify without your key** | Exact `model` string returned by `GET /v1/models`, per-model free eligibility on *your* account, and per-model RPM |

> [!warning] Mandatory pin step before Phase 2
> After creating an API key, run:
> ```bash
> curl -sS https://integrate.api.nvidia.com/v1/models -H "Authorization: Bearer $NVIDIA_API_KEY"
> ```
> Persist the exact `id` fields. Catalog slugs (e.g. `deepseek-v4-flash`) are **not always** identical to API `model` ids (often `org/slug`).

### 1.2 Account-level rate limits (verified community / forum)

| Claim | Status | Source |
|-------|--------|--------|
| Default free-tier **~40 RPM** | **Verified** (multiple NVIDIA forum threads, 2026) | [NVIDIA forum: 40 RPM](https://forums.developer.nvidia.com/t/api-rate-limit-increase-for-nvidia-nim/366043), [forum: 40 RPM](https://forums.developer.nvidia.com/t/request-for-api-rate-limit-and-credits-increase/375869) |
| Credit system largely replaced by rate limits | **Verified** (NVIDIA staff reply) | [forum: credits → rate limits](https://forums.developer.nvidia.com/t/request-more-4-000-credits-option-on-build-nvidia-com/344567) |
| Per-model RPM published in one global table | **Not verified** — NVIDIA: limits *vary by model* and are not fully published | Same staff reply |
| Some free endpoints cap context below marketing max (e.g. Nemotron 3 Nano free path ~131k vs 1M marketing) | **Community report** (not primary NVIDIA doc) | [r/LLMDevs](https://www.reddit.com/r/LLMDevs/comments/1r650o0/is_buildnvidiacom_unlimited/) |

**Inference for this project:** design mutation loop for **≤40 RPM**, serial mutations, exponential backoff on HTTP 429. Do not assume unlimited free tokens.

### 1.3 Previously noted IDs — verification table

| Prior note | Catalog presence (2026-07-11) | Free badge on catalog | Likely API `model` id (convention) | Context (model cards / marketing) | Coding evidence | Verdict |
|------------|-------------------------------|------------------------|-------------------------------------|-----------------------------------|-----------------|---------|
| `deepseek-v4-flash` | **Yes** — [deepseek-ai/deepseek-v4-flash](https://build.nvidia.com/deepseek-ai/deepseek-v4-flash) | **Yes** — “Downloadable Free Endpoint” on [models list](https://build.nvidia.com/models) | `deepseek-ai/deepseek-v4-flash` *(confirm via `/v1/models`)* | **1M tokens** advertised; MoE 284B / 13B active | Strong: LiveCodeBench ~55–92 depending on think mode; SWE-Verified ~74–79; SWE Multilingual ~70–73 ([model page benchmarks](https://build.nvidia.com/deepseek-ai/deepseek-v4-flash)) | **Primary coder candidate** |
| `mistral-nemotron` | **Yes** — [mistral-nemotron](https://build.nvidia.com/mistral-nemotron) | Listed; free badge **not independently re-read on card** in this pass | Often `mistralai/mistral-nemotron` or NVIDIA slug — **unconfirmed** | Agent/coding marketing | Built for agentic + coding ([catalog blurb](https://build.nvidia.com/models)) | **Viable fallback if free on your account** |
| `glm-5.2` | **Yes** — [glm-5.2](https://build.nvidia.com/models) | **Yes** — Free / Downloadable Free Endpoint on recent list | Often `z-ai/glm-5.2` or similar — **unconfirmed** | Agentic + coding flagship (marketing) | Catalog: agentic, coding, long-horizon reasoning | **Strong coder alt if free** |
| `minimax-m2.7` | **Yes** — [minimax-m2.7](https://build.nvidia.com/minimax-m2.7) | Community lists as free-catalog model | Community example: `minimaxai/minimax-m2.7` ([FB/NVIDIA Build guide](https://www.facebook.com/groups/icthubkenya/posts/4322344731242180/)) | Coding + reasoning (marketing) | Catalog: coding, reasoning, office | **Coder fallback candidate** |
| `nemotron-3-nano-30b-a3b` | **Yes** — [nvidia/nemotron-3-nano-30b-a3b](https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b) | **Yes** — Downloadable Free Endpoint | `nvidia/nemotron-3-nano-30b-a3b` *(confirm)* | Card: up to **1M** / practical **128K–256K** inputs; free tier may cap lower | LiveCodeBench **68.3**; SWE-Bench (OpenHands) **38.8** ([model card](https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b)) | **Excellent critic / secondary coder** |
| `gpt-oss-20b` | **Yes** — [gpt-oss-20b](https://build.nvidia.com/gpt-oss-20b) | Present; free status **confirm on account** | Often `openai/gpt-oss-20b` — **unconfirmed** | Efficient reasoning MoE (marketing) | Smaller sibling of gpt-oss-120b; used as baseline in Nemotron card | **Critic / summarizer candidate** |
| `llama-3.1-8b-instruct` | **Yes** — [llama-3.1-8b-instruct](https://build.nvidia.com/llama-3_1-8b-instruct) | Long-standing NIM catalog model; free on many trial keys historically | `meta/llama-3.1-8b-instruct` ([NIM API docs example](https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html)) | Typically **128K** class for Llama 3.1 | Solid general instruct; weaker pure coding than DeepSeek V4 / GLM-class | **Summarizer / cheap critic** |
| `gemma-2-2b-it` | **Yes** — [gemma-2-2b-it](https://build.nvidia.com/gemma-2-2b-it) | Present | Often `google/gemma-2-2b-it` — **unconfirmed** | Small edge SLM | Fast, weak coding | **Summarizer only** |

**None of the eight prior notes were “missing from the catalog” as of this survey.**  
**Renames:** use `org/slug` form, not bare slug, unless `/v1/models` says otherwise.  
**Free status:** badges on the public catalog are **strong evidence** for deepseek-v4-flash, glm-5.2 family, nemotron-3-nano, and many others — but **final free eligibility is account- and time-dependent**. If a model returns 402/403/payment errors, demote it immediately.

### 1.4 Recommended pin set (defaults for config)

> [!success] Live-verified 2026-07-11
> Account `GET /v1/models` returned **121** ids. Chat smoke OK on primary trio. Details: [[NIM Pin Log]].

| Role | Pick | Exact API `model` id | Why |
|------|------|----------------------|-----|
| **Primary coder** | DeepSeek V4 Flash | `deepseek-ai/deepseek-v4-flash` | Present on account; chat OK; coding-optimized ([page](https://build.nvidia.com/deepseek-ai/deepseek-v4-flash)) |
| **Fallback coder** | Nemotron 3 Nano 30B-A3B | `nvidia/nemotron-3-nano-30b-a3b` | Present; chat OK; LiveCodeBench strong ([page](https://build.nvidia.com/nvidia/nemotron-3-nano-30b-a3b)) |
| **Critic** | Nemotron 3 Nano | `nvidia/nemotron-3-nano-30b-a3b` | Same model sequential OK under 40 RPM |
| **Summarizer** | Llama 3.1 8B Instruct | `meta/llama-3.1-8b-instruct` | Present; chat OK (`PONG`) |

**Alternates on this account:** `z-ai/glm-5.2`, `minimaxai/minimax-m2.7`, `mistralai/mistral-nemotron`, `openai/gpt-oss-20b`, `google/gemma-2-2b-it`.

### 1.5 Operational config sketch (not implementation)

```yaml
# config/nim.yaml — values MUST be overwritten after GET /v1/models
nim:
  base_url: "https://integrate.api.nvidia.com/v1"
  free_only: true
  max_rpm: 40
  models:
    coder_primary: "deepseek-ai/deepseek-v4-flash"
    coder_fallback: "nvidia/nemotron-3-nano-30b-a3b"
    critic: "nvidia/nemotron-3-nano-30b-a3b"
    summarizer: "meta/llama-3.1-8b-instruct"
  mutation:
    max_tokens: 4096
    temperature: 0.2
    timeout_s: 120
  backoff:
    initial_s: 2
    max_s: 60
    on_status: [429, 503]
```

### 1.6 Residual risks (NIM)

- Catalog free badges change without notice.  
- Marketing context (1M) ≠ free-tier context cap.  
- High think/reasoning modes increase latency and may thrash 40 RPM budgets.  
- Empty `model=""` in some NVIDIA page snippets — **do not trust page templates**; trust `/v1/models`.

---

## 2. Literature comparison matrix

### 2.1 Comparison table

| System | Self-rewrite? | Body? | Archive? | Sandbox? | **Steal** | **Ignore** |
|--------|---------------|-------|----------|----------|-----------|------------|
| **Darwin Gödel Machine** ([arXiv:2505.22954](https://arxiv.org/abs/2505.22954), [sakana.ai/dgm](https://sakana.ai/dgm/)) | **Yes** — agent rewrites own code; FM proposes edits | Weak / coding-agent tools, not grid ALife | **Yes** — growing archive of agents; sample parent by performance + novelty | **Yes** — sandboxed eval, limited web, human oversight | Empirical accept-only mutations; archive of variants; parent sampling; frozen base FM; lineage/traceability; safety section practices | Full SWE-bench scope; open web tools; unconstrained codebase mutation; multi-week DGX-scale loops |
| **Avida** ([ALife encyclopedia](https://alife.org/encyclopedia/digital-evolution/avida/)) | Evolves program genomes (not LLM) | **Yes** — lattice cells, resources, hardware | Population / genealogy of digital organisms | Lab isolation by design (no host OS agency) | Embodiment + energy/resource fitness; population later; configurable experiments | CPU-instruction genomes; no LLM; different mutation operators |
| **Gödel machine** (Schmidhuber 2007; cited in DGM) | Theoretical self-rewrite with **proof** of benefit | Abstract | N/A | N/A (theory) | Framing: self-reference + improvement criterion | Formal proof requirement (intractable for us) |
| **POET / open-endedness** ([arXiv:1901.01753](https://arxiv.org/abs/1901.01753), Clune et al.) | Agents coevolve with **environments** | **Yes** — generated challenges | Archive of env–agent pairs | Research sims | Difficulty curriculum; diversity pressure; “stepping stones” language for Phase 5–6 | Full env generation in Phase 2; coevolution before single-task works |
| **AlphaEvolve** ([DeepMind blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/), [arXiv:2506.13131](https://arxiv.org/abs/2506.13131)) | LLM mutates programs; evolutionary loop | No organism body | Population of candidate programs | Automated evaluators (domain-specific) | **Automated evaluator as fitness oracle**; multi-objective scoring; evolve only what is measurable | Gemini-scale stack; inventing new math as Phase 2 goal |
| **FunSearch** (precursor; DeepMind 2023 — cited by AlphaEvolve) | Evolves functions via LLM + eval | No | Program database / island models | Eval harness | Small mutable surface + strict eval | Pure math discovery focus |
| **Our v0 target** (frozen) | Yes (LLM + whitelist) | Grid body | Lineage archive (single active) | Subprocess→harden | — | — |

### 2.2 Takeaways by system (3–5 each)

#### Darwin Gödel Machine

1. **Empirical > proof:** accept changes only if benchmarks improve — maps 1:1 to our frozen evaluator + ε.  
2. **Archive beats hill-climbing the latest only:** DGM ablations without archive underperform ([HTML paper](https://arxiv.org/html/2505.22954v3)). Steal: keep rejected/accepted parents in SQLite even with one *active* lineage.  
3. **Parent selection = performance × novelty:** sigmoid on score + offspring penalty — useful later for Phase 5.  
4. **Safety package:** sandbox, time limits, limited network, human oversight, traceable lineage ([Sakana safety notes](https://sakana.ai/dgm/)).  
5. **Ignore for v0:** self-modifying the *meta* agent’s full tool stack and SWE-bench scale.

#### Avida

1. Digital organisms need **bodies + limited resources** for meaningful selection — validates grid energy/food design.  
2. Fitness can be ecological (survive/reproduce), not only task accuracy — we defer pure open-ended fitness (D12).  
3. Config-driven experiments beat hard-coded worlds — keep world/fitness in frozen config.  
4. Genealogy tracking is first-class — align with our lineage tables.  
5. Ignore CPU-instruction ISA mutation mechanics.

#### Gödel machine (theory)

1. Ideal: rewrite only when **provably** better — we substitute empirical multi-seed tests.  
2. Self-reference requires a **clear boundary** between self and environment — our kernel/genome split.  
3. Ignore formal theorem-proving loop.

#### POET / open-endedness

1. Progress often needs **new challenges**, not only better agents — Phase 6 curriculum idea.  
2. Preserve diversity of stepping stones — archive rejected genomes with scores.  
3. Coevolution is powerful but premature before Bcw > B0 on a fixed task.  
4. Ignore generating environments in Phase 2.

#### AlphaEvolve / FunSearch-style evolutionary code search

1. **LLM proposes, evaluator disposes** — identical philosophy to our genomic loop.  
2. Keep mutation surface small and scores automatic.  
3. Multi-objective scores (quality + efficiency) — we already have weighted fitness terms.  
4. Ignore proprietary Gemini infrastructure and non-embodied math-only goals.

### 2.3 Must-steal shortlist (Phase 2)

| Steal | From | Our mapping |
|-------|------|-------------|
| Empirical accept gate | DGM / AlphaEvolve | Frozen evaluator + ε |
| Full lineage archive (even single active) | DGM | SQLite genomes + artifacts |
| Sandbox + no host write | DGM | Containment §3 |
| Small mutable surface | FunSearch / our D3 | Whitelist modules only |
| Ablations without self-improve / without archive | DGM paper | B0/Bw/Bc/Bcw + archive logging |
| Resource-limited body | Avida | Energy + grid |

---

## 3. Windows containment recommendation (threat model draft)

### 3.1 Threat model (v0 organism code)

| Threat | Severity | Example |
|--------|----------|---------|
| Host FS read/write outside workspace | **Critical** | Steal `.env`, encrypt files |
| Network egress | **Critical** | Exfil, C2, package pull |
| Edit evaluator / kernel | **Critical** | Fitness cheating (also architectural) |
| Resource exhaustion | High | Memory bomb, fork loop |
| Escape via native extensions | High | `ctypes` load arbitrary DLL |
| Side-channel / timing only | Low–Med | Ignore for Phase 2 |

**Invariant:** organism code must not touch host FS/network; must not edit evaluator/sandbox.

### 3.2 Option comparison (Windows 11 host)

| Option | Network block | Memory/CPU limits | FS isolation | Kill reliability | Setup friction |
|--------|---------------|-------------------|--------------|------------------|----------------|
| **(a) Subprocess + AST/import allowlist only** | **Weak** — pure Python can still open sockets unless OS-blocked | **Weak** — soft timeouts only | **Weak** — full user FS by default | Medium (terminate process tree hard on Windows) | **Lowest** |
| **(b) Subprocess inside Windows Job Object** | **Weak alone** — Job Objects limit CPU/memory/process count, **not** a full network/FS jail | **Good** — job memory/CPU process limits ([Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)) | **Weak** — still same user token | **Good** — kill job = kill tree | Low–medium (Win32 API / pywin32) |
| **(c) Docker Desktop container** | **Strong** — `--network none` | **Strong** — `--memory`, `--cpus` ([resource constraints](https://docs.docker.com/config/containers/resource-constraints/); Windows/WSL caveats) | **Strong** — bind-mount only workspace | **Strong** — `docker kill` | **Higher** — install Docker Desktop, WSL2 backend, image pull |
| **(d) WSL2 (raw distro, no Docker)** | Medium — can drop net with careful setup; easy to misconfigure | Medium — `.wslconfig` global caps ([WSL config](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)) | Medium — Linux FS separate; Windows drives still mountable (`/mnt/c`) if enabled | Medium | Medium |

**Verified fact:** Windows containers use job objects for resource controls ([MS docs](https://learn.microsoft.com/en-us/virtualization/windowscontainers/manage-containers/resource-controls)).  
**Inference:** Docker (Linux containers on WSL2) is the practical isolation unit on Win11 developer machines.

### 3.3 Recommendation for Phase 2 — **exactly one**

# **(c) Docker Desktop (Linux container) + minimal image + `--network none` + bind-mount workspace only**

**Rationale (aligned with frozen “subprocess first” *intent* without violating the safety invariant):**

1. Options **(a)** and **(b)** cannot honestly claim “no network / no host FS” for untrusted LLM-written Python on Windows. That would break the project’s #1 invariant on day one.  
2. Docker gives **network none**, **memory/CPU**, **filesystem jail**, and a reliable kill switch with moderate setup cost on Win11.  
3. Implement the *same* import allowlist + AST checks **inside** the container as defense-in-depth (treat Docker as outer wall, allowlist as inner wall).  
4. Kernel evaluator stays **on the host** (or a second trusted container) with **read-only** access to candidate artifacts — organism never imports evaluator code.

**Phase 2 container profile (proposal):**

```text
image: python:3.12-slim  (or custom: python + numpy only)
run: docker run --rm --network none --memory 512m --cpus 1 \
     --read-only --tmpfs /tmp:rw,size=64m \
     -v <candidate_workspace>:/work:ro \
     -w /work \
     <image> python -c "..."   # or entrypoint runner
```

- No outbound network.  
- Read-only root + small tmpfs.  
- Only whitelist pure modules: `math`, `random`, `typing`, `collections`, `numpy` (if weights use numpy).  
- Wall-clock timeout from host via `docker run` + kill.

### 3.4 Residual risks (even with Docker)

| Residual risk | Mitigation |
|---------------|------------|
| Docker Desktop / WSL2 not installed | Document as hard Phase 2 prerequisite; fail closed if Docker missing |
| Container breakout (rare) | Keep image minimal; no privileged; no docker.sock mount |
| LLM generates code that DoS Docker daemon | Global concurrency = 1 candidate; host watchdog |
| Evaluator compromised if colocated badly | Never mount kernel source into organism container |
| Windows Defender / path length issues | Use short workspace paths under project `artifacts/` |
| User runs Phase 2 without Docker “for speed” | CI/config flag `REQUIRE_DOCKER=1` default true |

### 3.5 What about the freeze “subprocess first”?

**Interpretation (not a redesign):** Phase 0 “subprocess + allowlist” is the **logical isolation API** (spawn untrusted code with limits). On Windows 11, the **implementation** of that API that meets the safety invariant is **Docker-backed execution**, not bare `subprocess.Popen` to host Python. Job Objects can wrap the docker client process or be a later host-hardening add-on, not the primary jail.

---

## 4. Parameter pre-registration proposal

> [!success] Pre-registration
> Lock these values in `config/experiment_v0.yaml` **before** the first mutation run. Changing them mid-experiment invalidates B0/Bw/Bc/Bcw comparisons unless you start a new `run_id`.

### 4.1 World & episodes

| Parameter | Value | Justification |
|-----------|-------|---------------|
| Grid size | **24×24** | Between 16–32; enough sparse food without long horizons |
| Episode length `T` | **200** ticks | Long enough for path planning; short enough for multi-seed eval |
| Food density | **~4%** of cells (~23 food on 24²) | Sparse → greedy seed underperforms |
| Energy max | **100** | Simple normalization for w3 |
| Energy start | **50** | Mid-range; death is real risk |
| Energy drain / move | **1** | Movement has cost |
| Energy drain / rest | **0.5** | Rest cheaper but no food |
| Forage success | +**15** energy if food present | Meaningful reward pulse |
| Actions | `N,S,E,W,forage,rest,noop` | Frozen action set |

### 4.2 Fitness formula (frozen evaluator)

```text
episode_score =
    w1 * food_collected
  + w2 * (ticks_survived / T)
  + w3 * (final_energy / energy_max)
  - w4 * invalid_actions
  - w5 * wall_bumps

fitness = mean_i(episode_score_i) - λ * std_i(episode_score_i)
```

| Weight | Value | Justification |
|--------|------:|---------------|
| `w1` (food) | **3.0** | Primary task signal — collect resources |
| `w2` (survival) | **1.0** | Prefer living full episode without dominating food |
| `w3` (final energy) | **0.5** | Soft efficiency; not farmable as sole objective |
| `w4` (invalid action) | **0.25** | Penalize contract breaks without total wipe |
| `w5` (wall bump) | **0.05** | Mild shaping against thrashing borders |
| `λ` (std penalty) | **0.15** | Prefer stable multi-seed policies over lottery winners |

**Acceptance:**

| Param | Value | Justification |
|-------|------:|---------------|
| `ε` | **0.05** absolute on fitness units | ~ small but non-zero improvement; avoids noise accepts |
| Crash / timeout / sandbox violation | fitness **N/A** → **reject** | Safety first |
| `δ` (success claim vs B0) | **+0.30** holdout fitness | Pre-registered “Phase 2 works” bar (≈ one solid food + survival edge) |

### 4.3 Evaluation protocol

| Param | Value | Justification |
|-------|------:|---------------|
| Eval episodes `N` | **8** | Multi-seed without exploding NIM time |
| Train seeds | **8** fixed: `{0,1,2,3,4,5,6,7}` | Reproducible parent ranking |
| Holdout seeds | **8** fixed: `{100,101,102,103,104,105,106,107}` | Overfit detector; never used for accept |
| Accept uses | Train seeds only | Holdout only for reporting / δ |
| Episode timeout (wall) | **5 s** inside container | Kill hung policies |
| Candidate CPU | **1** | Fairness |
| Candidate RAM | **512 MB** | Cap bombs |

### 4.4 Weight module (D5) — recommendation

# **Recommend: numpy-only linear scorer** (not torch)

| Choice | Decision |
|--------|----------|
| Module | `weights`: vector `θ ∈ R^d` |
| Features `φ(obs)` | Hand-built: local food indicators (5×5 flattened binary), own energy/energy_max, bias → **d ≈ 5×5+2 = 27** |
| Action scores | `score(a) = θ · φ_a` or shared θ with action-specific feature slices |
| Policy mix | ε-greedy over legal actions: `ε_explore=0.1` during life; greedy at eval **or** keep same ε for realism — **pre-register: ε_explore=0.05 at eval, 0.1 in training episodes** |
| Update rule | **REINFORCE-lite / bandit-style:** after each episode (or every K=20 steps),  
  `θ ← θ + α * (G - b) * ∇log π` with baseline `b` = exponential moving average of return;  
  simpler alt if unstable: **sliding-window preference**: increment θ components of actions that preceded food within last L=10 ticks |
| Learning rate `α` | **0.05** |
| θ init | `0` or `N(0, 0.01)` — **pre-register N(0, 0.01)`** |
| θ clip | `‖θ‖∞ ≤ 5` | Stability |

**Why not torch**

- Torch expands import surface (DLL, CUDA probes) and container size — conflicts with tight sandbox.  
- Grid toy task does not need deep nets.  
- Numpy is enough for dual-learning ablations (Bw vs Bc).

**Genome may still mutate** how features are built (`heuristics.py` / `memory_hooks.py`) while θ stays phenotype.

### 4.5 Genomic loop defaults

| Param | Value | Justification |
|-------|------:|---------------|
| Mutation trigger | Every **M=10** completed episodes **or** plateau **P=20** episodes without accept | Schedule + plateau |
| Max patch lines | **80** | Prefer small diffs |
| Max mutations / run | **30** | Free-tier RPM + science budget |
| NIM max_tokens | **4096** | Enough for 1–2 modules |
| Temperature (coder) | **0.2** | Conservative patches |
| Critic | Off in Phase 2 default; on in Phase 3 | Scope control |

### 4.6 Ablation run lengths (matched budget)

| Ablation | Episodes | Mutations allowed |
|----------|---------:|-------------------|
| B0 | 200 | 0 |
| Bw | 200 | 0 (weights on) |
| Bc | 200 | ≤30 (weights reset each episode or frozen at 0 — **pre-register: reset θ each episode**) |
| Bcw | 200 | ≤30 (θ persists within generation, re-init on new genome) |

Wall-clock secondary budget: stop at **4 hours** per ablation if unfinished.

### 4.7 Config blob (paste target)

```yaml
# config/experiment_v0.prereg.yaml
world:
  grid: [24, 24]
  T: 200
  food_density: 0.04
  energy_max: 100
  energy_start: 50
  drain_move: 1.0
  drain_rest: 0.5
  forage_energy: 15.0

fitness:
  w1: 3.0
  w2: 1.0
  w3: 0.5
  w4: 0.25
  w5: 0.05
  lambda_std: 0.15
  epsilon_accept: 0.05
  delta_success: 0.30

eval:
  N: 8
  train_seeds: [0, 1, 2, 3, 4, 5, 6, 7]
  holdout_seeds: [100, 101, 102, 103, 104, 105, 106, 107]
  episode_timeout_s: 5
  container_memory: 512m
  container_cpus: 1

weights:
  backend: numpy_linear
  d_features: 27
  alpha: 0.05
  init_std: 0.01
  clip_abs: 5.0
  explore_train: 0.10
  explore_eval: 0.05
  update: reinforce_lite_ema_baseline

genomic:
  mutate_every_episodes: 10
  plateau_episodes: 20
  max_mutations: 30
  max_patch_lines: 80

nim:
  coder_primary: "deepseek-ai/deepseek-v4-flash"
  coder_fallback: "nvidia/nemotron-3-nano-30b-a3b"
  critic: "nvidia/nemotron-3-nano-30b-a3b"
  summarizer: "meta/llama-3.1-8b-instruct"
  max_rpm: 40
```

Machine files: `config/nim.pinned.yaml` · secrets: `.env` (not in vault).

---

## Cross-links

[[Home]] · [[System Map]] · [[NIM Pin Log]] · [[Open Decisions]] · [[Research Brief]] · [[Roadmap]] · [[Artifact Management]] · [[References]]

---

## Phase 1 checklist

- [x] NIM candidates surveyed (catalog 2026-07-11)  
- [x] **Live** `GET /v1/models` — 121 models; pins locked → [[NIM Pin Log]]  
- [x] Literature matrix  
- [x] Windows containment recommendation (**Docker**)  
- [x] Pre-registration defaults  
- [x] Chat smoke: coder primary + fallback + summarizer  
- [x] Docker `--network none` smoke (`python_ok`, `network_blocked`, `smoke_pass`)  
- [x] API key stored in repo-root `.env` (gitignored); `.env.example` committed  

**Phase 2 unblocked** for scaffold (still pre-implementation until you ask to code).