"""Numpy-only linear scorer (phenotype). Torch intentionally avoided for sandbox surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from organism.schemas import Action, Observation


@dataclass
class WeightConfig:
    alpha: float = 0.05
    init_std: float = 0.01
    clip_abs: float = 5.0
    explore_train: float = 0.10
    explore_eval: float = 0.05


class LinearScorer:
    """score(a) = θ_a · φ(obs); REINFORCE-lite with EMA baseline."""

    N_ACTIONS = len(Action)

    def __init__(self, feature_dim: int, cfg: WeightConfig, rng: np.random.Generator | None = None) -> None:
        self.cfg = cfg
        self.rng = rng or np.random.default_rng(0)
        self.feature_dim = feature_dim
        self.theta = self.rng.normal(0.0, cfg.init_std, size=(self.N_ACTIONS, feature_dim)).astype(np.float64)
        self.baseline = 0.0
        self._trace: list[tuple[int, np.ndarray]] = []
        self._episode_return = 0.0

    def features(self, obs: Observation) -> np.ndarray:
        energy_norm = obs.energy / max(1e-6, obs.energy_max)
        phi = np.concatenate([obs.local_food.astype(np.float64), [energy_norm, 1.0]])
        if phi.size != self.feature_dim:
            # resize-safe if vision config changes mid-scaffold
            out = np.zeros(self.feature_dim, dtype=np.float64)
            n = min(self.feature_dim, phi.size)
            out[:n] = phi[:n]
            out[-1] = 1.0
            return out
        return phi

    def act(self, obs: Observation, explore: float) -> Action:
        phi = self.features(obs)
        logits = self.theta @ phi
        if self.rng.random() < explore:
            a = int(self.rng.integers(0, self.N_ACTIONS))
        else:
            a = int(np.argmax(logits))
        self._trace.append((a, phi))
        return Action(a)

    def on_reward(self, reward: float) -> None:
        self._episode_return += float(reward)

    def end_episode(self) -> None:
        G = self._episode_return
        self.baseline = 0.9 * self.baseline + 0.1 * G
        adv = G - self.baseline
        for a, phi in self._trace:
            self.theta[a] += self.cfg.alpha * adv * phi
        np.clip(self.theta, -self.cfg.clip_abs, self.cfg.clip_abs, out=self.theta)
        self._trace.clear()
        self._episode_return = 0.0

    def save(self, path: Path) -> None:
        """Low-level npz write. Prefer organism.checkpoints.save_checkpoint for metadata."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            theta=self.theta,
            baseline=np.array([self.baseline], dtype=np.float64),
            feature_dim=np.array([self.feature_dim], dtype=np.int32),
            n_actions=np.array([self.N_ACTIONS], dtype=np.int32),
            version=np.array([1], dtype=np.int32),
        )

    def load(self, path: Path) -> None:
        path = Path(path)
        data = np.load(path)
        self.theta = np.array(data["theta"], dtype=np.float64, copy=True)
        self.baseline = float(data["baseline"][0]) if "baseline" in data else 0.0
        if "feature_dim" in data:
            self.feature_dim = int(data["feature_dim"][0])
        else:
            self.feature_dim = int(self.theta.shape[1])
