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
) -> CheckpointMeta:
    """
    Write:
      artifacts/weights/{id}.npz
      artifacts/weights/{id}.json   (sidecar metadata)
    Update:
      artifacts/weights/latest.json
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
) -> CheckpointMeta:
    """Train scorer on genome, optionally score train fitness, save checkpoint."""
    from organism.evaluator import evaluate
    from organism.genome_loader import make_policy_factory
    from organism.evaluator import run_episode

    factory = make_policy_factory(
        genome_dir,
        ablation=ablation if ablation in ("Bw", "Bcw") else "Bw",
        weight_cfg=wcfg,
        force_train=True,
    )
    policy = factory()
    episodes = 0
    for p in range(passes):
        for seed in train_seeds:
            run_episode(policy, world, seed + p * 10_000, train_weights=True)
            episodes += 1

    scorer = getattr(policy, "scorer", None)
    if scorer is None:
        from organism.world import GridWorld

        obs = GridWorld(world, train_seeds[0]).reset()
        scorer = LinearScorer(obs.feature_dim(), wcfg)
        policy.scorer = scorer

    train_fitness = None
    if fit_cfg is not None and eval_seeds is not None:
        # save temp then eval with frozen weights
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
        train_fitness = res.fitness
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    return save_checkpoint(
        scorer,
        artifacts_dir=artifacts_dir,
        genome_id=genome_id,
        label=label or f"train-{genome_id}",
        ablation=ablation,
        train_fitness=train_fitness,
        episodes_trained=episodes,
        weight_cfg=wcfg,
    )
