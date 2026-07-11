"""Weight checkpoint save / load / registry (phenotype artifacts)."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from organism.weights import LinearScorer, WeightConfig


CHECKPOINT_VERSION = 1


@dataclass
class CheckpointMeta:
    checkpoint_id: str
    path: str
    genome_id: str
    feature_dim: int
    n_actions: int
    sha256: str
    created_at: float
    label: str = ""
    train_fitness: float | None = None
    holdout_fitness: float | None = None
    ablation: str = "Bw"
    episodes_trained: int = 0
    config: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CheckpointMeta:
        return cls(
            checkpoint_id=str(d["checkpoint_id"]),
            path=str(d["path"]),
            genome_id=str(d.get("genome_id", "")),
            feature_dim=int(d.get("feature_dim", 0)),
            n_actions=int(d.get("n_actions", 0)),
            sha256=str(d.get("sha256", "")),
            created_at=float(d.get("created_at", 0.0)),
            label=str(d.get("label", "")),
            train_fitness=d.get("train_fitness"),
            holdout_fitness=d.get("holdout_fitness"),
            ablation=str(d.get("ablation", "Bw")),
            episodes_trained=int(d.get("episodes_trained", 0)),
            config=d.get("config"),
        )


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def weights_root(artifacts_dir: Path) -> Path:
    root = Path(artifacts_dir) / "weights"
    root.mkdir(parents=True, exist_ok=True)
    return root


def meta_path_for(npz_path: Path) -> Path:
    return npz_path.with_suffix(".json")


def save_checkpoint(
    scorer: LinearScorer,
    *,
    artifacts_dir: Path,
    genome_id: str,
    label: str = "",
    ablation: str = "Bw",
    train_fitness: float | None = None,
    holdout_fitness: float | None = None,
    episodes_trained: int = 0,
    weight_cfg: WeightConfig | None = None,
    checkpoint_id: str | None = None,
    update_latest_best: bool = True,
) -> CheckpointMeta:
    """
    Write:
      artifacts/weights/{id}.npz
      artifacts/weights/{id}.json   (sidecar metadata)
    Update (if update_latest_best):
      artifacts/weights/latest.json
      artifacts/weights/best.json
      artifacts/weights/index.jsonl
    """
    cid = checkpoint_id or f"w_{_uid()}"
    root = weights_root(artifacts_dir)
    npz_path = root / f"{cid}.npz"

    cfg = weight_cfg or scorer.cfg
    config_blob = {
        "alpha": cfg.alpha,
        "init_std": cfg.init_std,
        "clip_abs": cfg.clip_abs,
        "explore_train": cfg.explore_train,
        "explore_eval": cfg.explore_eval,
    }
    np.savez_compressed(
        npz_path,
        theta=scorer.theta,
        baseline=np.array([scorer.baseline], dtype=np.float64),
        feature_dim=np.array([scorer.feature_dim], dtype=np.int32),
        n_actions=np.array([scorer.N_ACTIONS], dtype=np.int32),
        version=np.array([CHECKPOINT_VERSION], dtype=np.int32),
    )
    digest = _file_sha256(npz_path)
    meta = CheckpointMeta(
        checkpoint_id=cid,
        path=str(npz_path.resolve()),
        genome_id=genome_id,
        feature_dim=int(scorer.feature_dim),
        n_actions=int(scorer.N_ACTIONS),
        sha256=digest,
        created_at=time.time(),
        label=label or cid,
        train_fitness=train_fitness,
        holdout_fitness=holdout_fitness,
        ablation=ablation,
        episodes_trained=episodes_trained,
        config=config_blob,
    )
    meta_path_for(npz_path).write_text(json.dumps(meta.to_dict(), indent=2), encoding="utf-8")

    latest = {
        "checkpoint_id": cid,
        "path": meta.path,
        "meta_path": str(meta_path_for(npz_path).resolve()),
        "genome_id": genome_id,
        "updated_at": meta.created_at,
    }
    if update_latest_best:
        (root / "latest.json").write_text(json.dumps(latest, indent=2), encoding="utf-8")

        # best by train_fitness if present
        best_path = root / "best.json"
        should_write_best = True
        if best_path.exists() and train_fitness is not None:
            try:
                prev = json.loads(best_path.read_text(encoding="utf-8"))
                prev_f = prev.get("train_fitness")
                if prev_f is not None and float(prev_f) >= float(train_fitness):
                    should_write_best = False
            except Exception:
                pass
        if should_write_best and train_fitness is not None:
            best_path.write_text(
                json.dumps({**latest, "train_fitness": train_fitness}, indent=2),
                encoding="utf-8",
            )
        elif not best_path.exists():
            best_path.write_text(json.dumps(latest, indent=2), encoding="utf-8")

    index_path = root / "index.jsonl"
    with index_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta.to_dict()) + "\n")

    return meta


def load_scorer(
    path: Path | str,
    cfg: WeightConfig | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[LinearScorer, CheckpointMeta | None]:
    """Load LinearScorer from .npz; return optional sidecar meta."""
    path = Path(path)
    if path.is_dir():
        raise IsADirectoryError(path)
    if not path.exists():
        # try resolve via id
        raise FileNotFoundError(path)

    data = np.load(path)
    feature_dim = int(data["feature_dim"][0]) if "feature_dim" in data else int(data["theta"].shape[1])
    scorer = LinearScorer(feature_dim, cfg or WeightConfig(), rng=rng)
    scorer.theta = np.array(data["theta"], dtype=np.float64, copy=True)
    scorer.baseline = float(data["baseline"][0]) if "baseline" in data else 0.0
    if scorer.theta.shape != (scorer.N_ACTIONS, feature_dim):
        # tolerate shape if action count matches
        if scorer.theta.shape[0] != scorer.N_ACTIONS:
            raise ValueError(
                f"checkpoint action dim {scorer.theta.shape[0]} != {scorer.N_ACTIONS}"
            )
        scorer.feature_dim = scorer.theta.shape[1]

    meta = None
    mp = meta_path_for(path)
    if mp.exists():
        meta = CheckpointMeta.from_dict(json.loads(mp.read_text(encoding="utf-8")))
    return scorer, meta


def resolve_checkpoint_path(artifacts_dir: Path, ref: str) -> Path:
    """
    Resolve a checkpoint reference:
      - absolute/relative path to .npz
      - checkpoint id (w_xxxx)
      - 'latest' or 'best'
    """
    root = weights_root(artifacts_dir)
    if ref in ("latest", "best"):
        pointer = root / f"{ref}.json"
        if not pointer.exists():
            raise FileNotFoundError(f"no {ref} checkpoint pointer at {pointer}")
        data = json.loads(pointer.read_text(encoding="utf-8"))
        return Path(data["path"])

    p = Path(ref)
    if p.exists():
        return p
    cand = root / f"{ref}.npz"
    if cand.exists():
        return cand
    cand2 = root / ref
    if cand2.exists():
        return cand2
    raise FileNotFoundError(f"checkpoint not found: {ref}")


def list_checkpoints(artifacts_dir: Path) -> list[CheckpointMeta]:
    root = weights_root(artifacts_dir)
    metas: list[CheckpointMeta] = []
    for meta_file in sorted(root.glob("w_*.json")):
        try:
            metas.append(CheckpointMeta.from_dict(json.loads(meta_file.read_text(encoding="utf-8"))))
        except Exception:
            continue
    # also index.jsonl entries not already loaded
    index = root / "index.jsonl"
    if index.exists():
        seen = {m.checkpoint_id for m in metas}
        for line in index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                if d.get("checkpoint_id") not in seen:
                    metas.append(CheckpointMeta.from_dict(d))
                    seen.add(d["checkpoint_id"])
            except Exception:
                continue
    metas.sort(key=lambda m: m.created_at, reverse=True)
    return metas


def _bootstrap_from_heuristics(
    scorer: LinearScorer,
    *,
    genome_dir: Path,
    world,
    wcfg: WeightConfig,
    seeds: list[int],
    n_episodes: int,
) -> int:
    """Behavioral cloning from seed heuristics so weights don't start as pure thrash."""
    from organism.genome_loader import make_policy_factory
    from organism.world import GridWorld

    if n_episodes <= 0:
        return 0
    teacher_f = make_policy_factory(
        genome_dir, ablation="B0", weight_cfg=wcfg, force_train=False
    )
    teacher = teacher_f()
    alpha = float(getattr(wcfg, "bootstrap_alpha", 0.05))
    done_eps = 0
    seed_cycle = list(seeds) or [0]
    for i in range(n_episodes):
        seed = int(seed_cycle[i % len(seed_cycle)]) + 50_000 + i
        env = GridWorld(world, seed=seed)
        obs = env.reset()
        teacher.reset(seed)
        # ensure scorer feature dim matches
        if scorer.feature_dim != obs.feature_dim():
            # rebuild scorer in place if vision mismatch (shouldn't happen mid-run)
            pass
        for _ in range(max(1, int(world.T))):
            a = teacher.act(obs)
            scorer.imitate(obs, a, alpha=alpha)
            result = env.step(a)
            if result.done:
                break
            obs = env.observe()
        done_eps += 1
    scorer._trace.clear()
    scorer._rewards.clear()
    scorer._episode_return = 0.0
    return done_eps


def train_and_checkpoint(
    *,
    genome_dir: Path,
    world,
    wcfg: WeightConfig,
    train_seeds: list[int],
    artifacts_dir: Path,
    genome_id: str,
    passes: int = 2,
    ablation: str = "Bw",
    label: str = "",
    fit_cfg=None,
    eval_seeds: list[int] | None = None,
    holdout_seeds: list[int] | None = None,
    keep_if_beats_b0: bool = False,
    b0_margin: float = 0.0,
) -> CheckpointMeta:
    """
    Train scorer: optional heuristic BC bootstrap → REINFORCE passes → checkpoint.
    Bootstrap prevents random-init weights from erasing competent seed behavior.

    If keep_if_beats_b0 and holdout_seeds+fit_cfg provided: after training, compare
    holdout Bw vs B0; if Bw does not beat B0+margin, still save checkpoint but set
    meta["discarded_for_eval"]=True and do not update latest/best pointers.
    """
    from organism.evaluator import evaluate, run_episode
    from organism.genome_loader import make_policy_factory
    from organism.world import GridWorld

    factory = make_policy_factory(
        genome_dir,
        ablation=ablation if ablation in ("Bw", "Bcw") else "Bw",
        weight_cfg=wcfg,
        force_train=True,
    )
    policy = factory()
    # Materialize scorer on a dummy obs before bootstrap
    probe = GridWorld(world, seed=int(train_seeds[0] if train_seeds else 0)).reset()
    if hasattr(policy, "_ensure_scorer"):
        scorer = policy._ensure_scorer(probe)  # type: ignore[attr-defined]
    else:
        scorer = LinearScorer(LinearScorer.feature_dim_for(probe), wcfg)
        policy.scorer = scorer  # type: ignore[attr-defined]

    bootstrap_n = int(getattr(wcfg, "bootstrap_episodes", 8) or 0)
    boot_eps = _bootstrap_from_heuristics(
        scorer,
        genome_dir=genome_dir,
        world=world,
        wcfg=wcfg,
        seeds=list(train_seeds),
        n_episodes=bootstrap_n,
    )

    def _train_fit_snapshot() -> float | None:
        if fit_cfg is None or not eval_seeds:
            return None
        tmp = weights_root(artifacts_dir) / "_tmp_train.npz"
        scorer.save(tmp)
        res = evaluate(
            make_policy_factory(
                genome_dir,
                ablation="Bw",
                weight_cfg=wcfg,
                weight_path=tmp,
                force_train=False,
            ),
            world,
            fit_cfg,
            eval_seeds,
            train_weights=False,
        )
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return float(res.fitness)

    # Keep best weights — REINFORCE often *destroys* good BC bootstrap
    best_theta = np.array(scorer.theta, copy=True)
    best_baseline = float(scorer.baseline)
    best_fit = _train_fit_snapshot()
    episodes = boot_eps

    for p in range(passes):
        for seed in train_seeds:
            run_episode(policy, world, seed + p * 10_000, train_weights=True)
            episodes += 1
        # After each pass, keep only if train fitness improved
        cur = _train_fit_snapshot()
        if cur is not None and (best_fit is None or cur > best_fit + 1e-6):
            best_fit = cur
            best_theta = np.array(scorer.theta, copy=True)
            best_baseline = float(scorer.baseline)

    scorer = getattr(policy, "scorer", None) or scorer
    scorer.theta = best_theta
    scorer.baseline = best_baseline
    train_fitness = best_fit if best_fit is not None else _train_fit_snapshot()

    update_pointers = True
    extra_meta: dict[str, Any] = {}
    if keep_if_beats_b0 and fit_cfg is not None and holdout_seeds:
        from organism.sandbox import evaluate_genome
        from organism.sandbox import SandboxConfig

        tmp = weights_root(artifacts_dir) / "_tmp_holdout.npz"
        scorer.save(tmp)
        sb = SandboxConfig(mode="host", episode_isolation=False, require_docker=False)
        b0 = evaluate_genome(
            genome_dir,
            world=world,
            fit=fit_cfg,
            wcfg=wcfg,
            seeds=list(holdout_seeds),
            ablation="B0",
            sandbox=sb,
            train_weights=False,
            force_host=True,
            best_of_phenotype=False,
        )
        bw = evaluate_genome(
            genome_dir,
            world=world,
            fit=fit_cfg,
            wcfg=wcfg,
            seeds=list(holdout_seeds),
            ablation="Bw",
            sandbox=sb,
            train_weights=False,
            weight_path=tmp,
            force_host=True,
            best_of_phenotype=False,
        )
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        delta = float(bw.fitness) - float(b0.fitness)
        extra_meta["holdout_b0"] = float(b0.fitness)
        extra_meta["holdout_bw"] = float(bw.fitness)
        extra_meta["holdout_delta_bw_minus_b0"] = delta
        if delta <= float(b0_margin):
            update_pointers = False
            extra_meta["discarded_for_eval"] = True
            extra_meta["discard_reason"] = (
                f"holdout Bw-B0={delta:+.4f} <= margin {b0_margin}"
            )

    meta = save_checkpoint(
        scorer,
        artifacts_dir=artifacts_dir,
        genome_id=genome_id,
        label=label or f"train-{genome_id}",
        ablation=ablation,
        train_fitness=train_fitness,
        episodes_trained=episodes,
        weight_cfg=wcfg,
        update_latest_best=update_pointers,
    )
    if extra_meta:
        # merge diagnostics into sidecar
        import json

        side = Path(meta.path).with_suffix(".json")
        try:
            data = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
            data.update(extra_meta)
            data["update_latest_best"] = update_pointers
            side.write_text(json.dumps(data, indent=2), encoding="utf-8")
            meta.holdout_fitness = extra_meta.get("holdout_bw")
        except Exception:
            pass
    return meta
