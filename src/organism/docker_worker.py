"""
In-container evaluation worker.

Invoked only inside the sandbox image with:
  PYTHONPATH=/app/src
  request at /job/request.json (read-only mount)
  genome at /genome
  optional weights at /weights/checkpoint.npz
  result printed as SEO_RESULT:<json> on stdout (no host rw mount)
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import asdict
from pathlib import Path


def main() -> int:
    job = Path("/job")
    req_path = job / "request.json"
    try:
        req = json.loads(req_path.read_text(encoding="utf-8"))
        from organism.evaluator import FitnessConfig, evaluate
        from organism.genome_loader import make_policy_factory
        from organism.weights import WeightConfig
        from organism.world import WorldConfig

        world = WorldConfig.from_dict(req.get("world", {}))
        fit = FitnessConfig.from_dict(req.get("fitness", {}), req.get("world", {}))
        wcfg_d = req.get("weights", {})
        wcfg = WeightConfig(
            alpha=float(wcfg_d.get("alpha", 0.05)),
            init_std=float(wcfg_d.get("init_std", 0.01)),
            clip_abs=float(wcfg_d.get("clip_abs", 5.0)),
            explore_train=float(wcfg_d.get("explore_train", 0.10)),
            explore_eval=float(wcfg_d.get("explore_eval", 0.05)),
        )
        genome_dir = Path(req.get("genome_dir", "/genome"))
        seeds = list(req.get("seeds", [0]))
        ablation = str(req.get("ablation", "Bc"))
        train_weights = bool(req.get("train_weights", False))
        weight_path = req.get("weight_path")
        wpath = Path(weight_path) if weight_path else None
        episode_timeout_s = float(req.get("episode_timeout_s", 5.0))

        factory = make_policy_factory(
            genome_dir,
            ablation=ablation,
            weight_cfg=wcfg,
            weight_path=wpath,
            force_train=train_weights,
        )
        result = evaluate(
            factory,
            world,
            fit,
            seeds,
            train_weights=train_weights,
            episode_timeout_s=episode_timeout_s,
        )
        payload = {
            "ok": True,
            "fitness": result.fitness,
            "mean_score": result.mean_score,
            "std_score": result.std_score,
            "seeds": result.seeds,
            "episodes": [asdict(ep) for ep in result.episodes],
            "isolated": True,
            "episode_timeout_s": episode_timeout_s,
        }
        # Size-bounded: single line JSON (host parses stdout; /tmp is 64m tmpfs if needed)
        print("SEO_RESULT:" + json.dumps(payload), flush=True)
        return 0
    except Exception as e:
        payload = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[:4000],
            "isolated": True,
        }
        print("SEO_RESULT:" + json.dumps(payload), flush=True)
        print(json.dumps(payload), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
