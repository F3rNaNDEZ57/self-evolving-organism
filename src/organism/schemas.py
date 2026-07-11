"""Frozen observation/action contracts. Genome must not redefine these."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import numpy as np


class Action(IntEnum):
    N = 0
    S = 1
    E = 2
    W = 3
    FORAGE = 4
    REST = 5
    NOOP = 6


ACTION_NAMES = {
    Action.N: "N",
    Action.S: "S",
    Action.E: "E",
    Action.W: "W",
    Action.FORAGE: "forage",
    Action.REST: "rest",
    Action.NOOP: "noop",
}

DELTAS = {
    Action.N: (-1, 0),
    Action.S: (1, 0),
    Action.E: (0, 1),
    Action.W: (0, -1),
}


@dataclass
class Observation:
    """Local view + body state exposed to the genome policy."""

    tick: int
    energy: float
    energy_max: float
    x: int
    y: int
    # flattened local food grid (1 = food, 0 = empty/out of bounds), row-major
    local_food: np.ndarray
    vision: int
    last_reward: float = 0.0
    alive: bool = True

    def feature_dim(self) -> int:
        # local food + energy_norm + bias
        return int(self.local_food.size) + 2


@dataclass
class StepResult:
    reward: float
    energy: float
    alive: bool
    food_collected: int
    invalid_action: bool
    wall_bump: bool
    done: bool
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodeSummary:
    seed: int
    score: float
    food_collected: int
    ticks_survived: int
    final_energy: float
    invalid_actions: int
    wall_bumps: int
    death_reason: str
