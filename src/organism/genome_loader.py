"""Load whitelist genome modules from a directory (seed or artifact snapshot)."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from organism.schemas import Action, Observation, StepResult
from organism.weights import WeightConfig


WHITELIST = ("policy.py", "heuristics.py", "memory_hooks.py")


def copy_genome(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in WHITELIST:
        s = src / name
        if not s.exists():
            raise FileNotFoundError(f"Missing genome module: {s}")
        shutil.copy2(s, dest / name)


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    # Caller manages sys.path for sibling imports
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def load_policy_class(genome_dir: Path) -> type:
    """Load Policy from genome_dir. Uses unique module names then aliases short names."""
    import uuid

    genome_dir = Path(genome_dir)
    uid = uuid.uuid4().hex[:8]
    short_names = ("heuristics", "memory_hooks", "policy")
    loaded: dict[str, ModuleType] = {}
    gdir = str(genome_dir.resolve())
    sys.path.insert(0, gdir)
    try:
        for mod_name, file_name in (
            ("heuristics", "heuristics.py"),
            ("memory_hooks", "memory_hooks.py"),
            ("policy", "policy.py"),
        ):
            path = genome_dir / file_name
            if not path.exists():
                raise FileNotFoundError(path)
            unique = f"seo_genome_{uid}_{mod_name}"
            mod = _load_module(path, unique)
            loaded[mod_name] = mod
            sys.modules[mod_name] = mod  # bare imports inside genome
        policy_mod = loaded["policy"]
        if not hasattr(policy_mod, "Policy"):
            raise AttributeError(f"{genome_dir}/policy.py must define class Policy")
        return policy_mod.Policy
    finally:
        if sys.path and sys.path[0] == gdir:
            sys.path.pop(0)
        # leave unique modules; clear short aliases so next load can rebind
        for sn in short_names:
            if sn in sys.modules and getattr(sys.modules[sn], "__file__", "").startswith(gdir):
                # only delete if it points at this genome dir
                pass



def make_policy_factory(
    genome_dir: Path,
    *,
    ablation: str,
    weight_cfg: WeightConfig | None = None,
    weight_path: Path | None = None,
    force_train: bool | None = None,
) -> Callable[[], Any]:
    """
    Ablation:
      B0  — heuristics only, no weight training
      Bw  — weights (+ optional training / checkpoint load)
      Bc  — heuristics only (code mutations)
      Bcw — weights + code mutations
    """
    Policy = load_policy_class(genome_dir)
    use_weights = ablation in ("Bw", "Bcw")
    train = ablation in ("Bw", "Bcw") if force_train is None else force_train
    explore = 0.05 if not train else 0.10
    wcfg = weight_cfg or WeightConfig()
    wpath = Path(weight_path) if weight_path else None

    def factory() -> Any:
        pol = Policy(use_weights=use_weights, weight_cfg=wcfg, explore=explore, train=train)
        if wpath is not None and use_weights and hasattr(pol, "load_weights"):
            pol.load_weights(wpath)
        elif wpath is not None and use_weights:
            # seed Policy without load_weights helper: set after first reset via scorer load
            pol._pending_weight_path = str(wpath)  # type: ignore[attr-defined]
        return pol

    return factory
