"""Numpy-only linear scorer (phenotype). Torch intentionally avoided for sandbox surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from organism.schemas import Action, Observation


@dataclass
class WeightConfig:
    alpha: float = 0.02
    init_std: float = 0.01
    clip_abs: float = 5.0
    explore_train: float = 0.10
    # Deterministic eval of learned policy (random eval was tanking Bw holdout)
    explore_eval: float = 0.0
    gamma: float = 0.99
    # Behavioral cloning episodes from seed heuristics before REINFORCE
    bootstrap_episodes: int = 12
    bootstrap_alpha: float = 0.08


class LinearScorer:
    """
    score(a) = θ_a · φ(obs).
    Features = local food map + engineered direction/energy stats (linear model can chase food).
    Train: optional BC bootstrap + REINFORCE with return-to-go.
    """

    N_ACTIONS = len(Action)
    # engineered tail: energy, food_here, N,S,E,W mass, visible, bias
    ENGINEERED = 8

    def __init__(self, feature_dim: int, cfg: WeightConfig, rng: np.random.Generator | None = None) -> None:
        self.cfg = cfg
        self.rng = rng or np.random.default_rng(0)
        self.feature_dim = feature_dim
        self.theta = self.rng.normal(0.0, cfg.init_std, size=(self.N_ACTIONS, feature_dim)).astype(np.float64)
        self.baseline = 0.0
        self._trace: list[tuple[int, np.ndarray]] = []
        self._rewards: list[float] = []
        self._episode_return = 0.0

    @staticmethod
    def compute_features(obs: Observation) -> np.ndarray:
        energy_norm = obs.energy / max(1e-6, obs.energy_max)
        food = obs.local_food.astype(np.float64).ravel()
        v = int(obs.vision)
        side = 2 * v + 1
        if food.size == side * side:
            grid = food.reshape(side, side)
            food_here = float(grid[v, v])
            n_mass = float(grid[:v, :].sum())
            s_mass = float(grid[v + 1 :, :].sum())
            w_mass = float(grid[:, :v].sum())
            e_mass = float(grid[:, v + 1 :].sum())
            visible = float(grid.sum())
        else:
            food_here = n_mass = s_mass = e_mass = w_mass = visible = 0.0
        eng = np.array(
            [energy_norm, food_here, n_mass, s_mass, e_mass, w_mass, visible, 1.0],
            dtype=np.float64,
        )
        return np.concatenate([food, eng])

    @classmethod
    def feature_dim_for(cls, obs: Observation) -> int:
        return int(obs.local_food.size) + cls.ENGINEERED

    def features(self, obs: Observation) -> np.ndarray:
        phi = self.compute_features(obs)
        if phi.size != self.feature_dim:
            out = np.zeros(self.feature_dim, dtype=np.float64)
            n = min(self.feature_dim, phi.size)
            out[:n] = phi[:n]
            out[-1] = 1.0
            return out
        return phi

    def act(self, obs: Observation, explore: float) -> Action:
        phi = self.features(obs)
        logits = self.theta @ phi
        if explore > 0 and self.rng.random() < explore:
            a = int(self.rng.integers(0, self.N_ACTIONS))
        else:
            a = int(np.argmax(logits))
        self._trace.append((a, phi.copy()))
        return Action(a)

    def on_reward(self, reward: float) -> None:
        r = float(reward)
        self._episode_return += r
        self._rewards.append(r)

    def end_episode(self) -> None:
        """REINFORCE with discounted return-to-go."""
        if not self._trace:
            self._rewards.clear()
            self._episode_return = 0.0
            return
        gamma = float(getattr(self.cfg, "gamma", 0.99) or 0.99)
        rewards = list(self._rewards)
        while len(rewards) < len(self._trace):
            rewards.append(0.0)
        rewards = rewards[: len(self._trace)]

        returns: list[float] = []
        G = 0.0
        for r in reversed(rewards):
            G = r + gamma * G
            returns.append(G)
        returns.reverse()

        ep_return = float(sum(rewards))
        self.baseline = 0.9 * self.baseline + 0.1 * ep_return
        alpha = float(self.cfg.alpha)
        for (a, phi), Gt in zip(self._trace, returns):
            adv = Gt - self.baseline
            self.theta[a] += alpha * adv * phi
        np.clip(self.theta, -self.cfg.clip_abs, self.cfg.clip_abs, out=self.theta)
        self._trace.clear()
        self._rewards.clear()
        self._episode_return = 0.0

    def imitate(self, obs: Observation, action: Action | int, alpha: float | None = None) -> None:
        """Multiclass logistic (softmax) behavioral cloning step toward teacher action."""
        a = int(action)
        if a < 0 or a >= self.N_ACTIONS:
            return
        phi = self.features(obs)
        lr = float(alpha if alpha is not None else getattr(self.cfg, "bootstrap_alpha", 0.08))
        logits = self.theta @ phi
        # stable softmax
        z = logits - float(np.max(logits))
        exp = np.exp(z)
        probs = exp / max(1e-12, float(exp.sum()))
        for j in range(self.N_ACTIONS):
            target = 1.0 if j == a else 0.0
            self.theta[j] += lr * (target - probs[j]) * phi
        np.clip(self.theta, -self.cfg.clip_abs, self.cfg.clip_abs, out=self.theta)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            theta=self.theta,
            baseline=np.array([self.baseline], dtype=np.float64),
            feature_dim=np.array([self.feature_dim], dtype=np.int32),
            n_actions=np.array([self.N_ACTIONS], dtype=np.int32),
            version=np.array([2], dtype=np.int32),
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
