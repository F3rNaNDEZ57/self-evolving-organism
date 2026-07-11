"""Frozen multi-seed fitness evaluator (kernel — not organism-writable)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

import numpy as np

from organism.schemas import Action, EpisodeSummary, Observation, StepResult
from organism.world import GridWorld, WorldConfig


class PolicyProtocol(Protocol):
    def reset(self, seed: int) -> None: ...
    def act(self, observation: Observation) -> Action | int: ...
    def on_step_result(self, result: StepResult) -> None: ...


@dataclass
class FitnessConfig:
    w1: float = 3.0
    w2: float = 1.0
    w3: float = 0.5
    w4: float = 0.25
    w5: float = 0.05
    lambda_std: float = 0.15
    epsilon_accept: float = 0.05
    delta_success: float = 0.30
    energy_max: float = 100.0
    T: int = 200

    @classmethod
    def from_dict(cls, d: dict[str, Any], world: dict[str, Any] | None = None) -> FitnessConfig:
        world = world or {}
        return cls(
            w1=float(d.get("w1", 3.0)),
            w2=float(d.get("w2", 1.0)),
            w3=float(d.get("w3", 0.5)),
            w4=float(d.get("w4", 0.25)),
            w5=float(d.get("w5", 0.05)),
            lambda_std=float(d.get("lambda_std", 0.15)),
            epsilon_accept=float(d.get("epsilon_accept", 0.05)),
            delta_success=float(d.get("delta_success", 0.30)),
            energy_max=float(world.get("energy_max", 100.0)),
            T=int(world.get("T", 200)),
        )


def episode_score(summary: EpisodeSummary, fit: FitnessConfig) -> float:
    return (
        fit.w1 * summary.food_collected
        + fit.w2 * (summary.ticks_survived / max(1, fit.T))
        + fit.w3 * (summary.final_energy / max(1e-6, fit.energy_max))
        - fit.w4 * summary.invalid_actions
        - fit.w5 * summary.wall_bumps
    )


def run_episode(
    policy: PolicyProtocol,
    world_cfg: WorldConfig,
    seed: int,
    train_weights: bool = False,
) -> EpisodeSummary:
    world = GridWorld(world_cfg, seed=seed)
    obs = world.reset()
    policy.reset(seed)
    death = "timeout"
    while True:
        action = policy.act(obs)
        result = world.step(action)
        if train_weights:
            policy.on_step_result(result)
        else:
            # still allow memory hooks without training
            try:
                policy.on_step_result(result)
            except Exception:
                pass
        if result.done:
            if not result.alive or world.energy <= 0:
                death = "energy"
            break
        obs = world.observe()

    summary = EpisodeSummary(
        seed=seed,
        score=0.0,
        food_collected=world.food_collected,
        ticks_survived=world.tick,
        final_energy=world.energy,
        invalid_actions=world.invalid_actions,
        wall_bumps=world.wall_bumps,
        death_reason=death,
    )
    return summary


@dataclass
class EvalResult:
    fitness: float
    mean_score: float
    std_score: float
    episodes: list[EpisodeSummary]
    seeds: list[int]


def evaluate(
    policy_factory: Callable[[], PolicyProtocol],
    world_cfg: WorldConfig,
    fit_cfg: FitnessConfig,
    seeds: list[int],
    train_weights: bool = False,
) -> EvalResult:
    episodes: list[EpisodeSummary] = []
    scores: list[float] = []
    for seed in seeds:
        policy = policy_factory()
        summary = run_episode(policy, world_cfg, seed, train_weights=train_weights)
        summary.score = episode_score(summary, fit_cfg)
        episodes.append(summary)
        scores.append(summary.score)
    arr = np.asarray(scores, dtype=np.float64)
    mean = float(arr.mean()) if len(arr) else 0.0
    std = float(arr.std(ddof=0)) if len(arr) else 0.0
    fitness = mean - fit_cfg.lambda_std * std
    return EvalResult(
        fitness=fitness,
        mean_score=mean,
        std_score=std,
        episodes=episodes,
        seeds=list(seeds),
    )
