"""Seed policy: greedy-ish food chase with noise — deliberately mediocre."""

from __future__ import annotations

import random

import numpy as np
from heuristics import nearest_food_direction, should_forage
from memory_hooks import SimpleMemory

from organism.schemas import Action, Observation, StepResult
from organism.weights import LinearScorer, WeightConfig


class Policy:
    """
    Frozen interface:
      reset(seed) -> None
      act(observation) -> Action
      on_step_result(result) -> None
    """

    def __init__(
        self,
        use_weights: bool = False,
        weight_cfg: WeightConfig | None = None,
        explore: float = 0.1,
        train: bool = False,
    ) -> None:
        self.use_weights = use_weights
        self.train = train
        self.explore = explore
        self.weight_cfg = weight_cfg or WeightConfig()
        self.memory = SimpleMemory()
        self.rng = random.Random(0)
        self.scorer: LinearScorer | None = None
        self._feature_dim: int | None = None
        self._pending_weight_path: str | None = None

    def load_weights(self, path: str) -> None:
        # path is str only — pathlib is forbidden in whitelist modules
        self._pending_weight_path = str(path)

    def reset(self, seed: int) -> None:
        self.rng.seed(seed)
        self.memory.reset()
        # keep scorer across episodes when training/eval with shared policy instance

    def _ensure_scorer(self, observation: Observation) -> LinearScorer:
        if self.scorer is None:
            self._feature_dim = observation.feature_dim()
            self.scorer = LinearScorer(
                self._feature_dim,
                self.weight_cfg,
                rng=np.random.default_rng(self.rng.randint(0, 10**9)),
            )
            if self._pending_weight_path:
                try:
                    self.scorer.load(self._pending_weight_path)
                except (OSError, FileNotFoundError, ValueError):
                    pass
        return self.scorer

    def act(self, observation: Observation) -> Action:
        if self.use_weights:
            scorer = self._ensure_scorer(observation)
            return scorer.act(observation, explore=self.explore)

        # Heuristic baseline (mediocre)
        if should_forage(observation) and self.rng.random() < 0.85:
            return Action.FORAGE
        direction = nearest_food_direction(observation)
        if direction is not None and self.rng.random() < 0.7:
            return direction
        if observation.energy < 15 and self.rng.random() < 0.4:
            return Action.REST
        # random walk / thrash
        return self.rng.choice(
            [Action.N, Action.S, Action.E, Action.W, Action.NOOP, Action.REST]
        )

    def on_step_result(self, result: StepResult) -> None:
        self.memory.on_step(result)
        if self.use_weights and self.scorer is not None:
            self.scorer.on_reward(result.reward)
            if result.done and self.train:
                self.scorer.end_episode()

    @property
    def scorer_public(self) -> LinearScorer | None:
        return self.scorer
