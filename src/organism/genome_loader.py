"""Load whitelist genome modules from a directory (seed or artifact snapshot)."""

from __future__ import annotations

import importlib.util
import shutil
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from organism.schemas import Action, Observation, StepResult
from organism.weights import WeightConfig

WHITELIST = ("policy.py", "heuristics.py", "memory_hooks.py")

# Serialize bare-name rebinding across concurrent loads in one process
_LOAD_LOCK = threading.RLock()


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
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def load_policy_class(genome_dir: Path) -> type:
    """
    Load Policy from genome_dir using unique module names.
    Bare names (policy/heuristics/memory_hooks) are aliased only during load
    and cleaned up afterward to prevent cross-genome contamination.
    """
    import uuid

    genome_dir = Path(genome_dir).resolve()
    uid = uuid.uuid4().hex[:8]
    short_names = ("heuristics", "memory_hooks", "policy")
    unique_keys = [f"seo_genome_{uid}_{n}" for n in short_names]
    gdir = str(genome_dir)
    loaded: dict[str, ModuleType] = {}

    with _LOAD_LOCK:
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
            # Drop short aliases that point at this genome (prevent contamination)
            for sn in short_names:
                mod = sys.modules.get(sn)
                if mod is None:
                    continue
                mf = getattr(mod, "__file__", None) or ""
                try:
                    if mf and str(Path(mf).resolve()).startswith(gdir):
                        del sys.modules[sn]
                except Exception:
                    # if resolve fails, still clear if unique name matches
                    if any(sys.modules.get(k) is mod for k in unique_keys):
                        del sys.modules[sn]
            # Drop unique modules — Policy class remains usable via reference
            for k in unique_keys:
                sys.modules.pop(k, None)


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
    wcfg = weight_cfg or WeightConfig()
    # Honor WeightConfig explore rates (eval default 0.0 — random eval was tanking Bw)
    explore = float(wcfg.explore_train if train else wcfg.explore_eval)
    wpath = Path(weight_path) if weight_path else None

    def factory() -> Any:
        pol = Policy(use_weights=use_weights, weight_cfg=wcfg, explore=explore, train=train)
        if wpath is not None and use_weights and hasattr(pol, "load_weights"):
            pol.load_weights(wpath)
        elif wpath is not None and use_weights:
            pol._pending_weight_path = str(wpath)  # type: ignore[attr-defined]
        return pol

    return factory
