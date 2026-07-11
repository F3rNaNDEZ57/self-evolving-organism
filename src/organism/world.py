"""Frozen grid world simulator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from organism.schemas import DELTAS, Action, Observation, StepResult


@dataclass
class WorldConfig:
    height: int = 24
    width: int = 24
    T: int = 200
    food_density: float = 0.04
    energy_max: float = 100.0
    energy_start: float = 50.0
    drain_move: float = 1.0
    drain_rest: float = 0.5
    forage_energy: float = 15.0
    vision: int = 2

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorldConfig:
        grid = d.get("grid", [24, 24])
        return cls(
            height=int(grid[0]),
            width=int(grid[1]),
            T=int(d.get("T", 200)),
            food_density=float(d.get("food_density", 0.04)),
            energy_max=float(d.get("energy_max", 100.0)),
            energy_start=float(d.get("energy_start", 50.0)),
            drain_move=float(d.get("drain_move", 1.0)),
            drain_rest=float(d.get("drain_rest", 0.5)),
            forage_energy=float(d.get("forage_energy", 15.0)),
            vision=int(d.get("vision", 2)),
        )


class GridWorld:
    def __init__(self, cfg: WorldConfig, seed: int) -> None:
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.food = np.zeros((cfg.height, cfg.width), dtype=np.int8)
        self.x = 0
        self.y = 0
        self.energy = cfg.energy_start
        self.tick = 0
        self.alive = True
        self.food_collected = 0
        self.invalid_actions = 0
        self.wall_bumps = 0
        self.last_reward = 0.0
        self._place()

    def _place(self) -> None:
        n_cells = self.cfg.height * self.cfg.width
        n_food = max(1, int(round(n_cells * self.cfg.food_density)))
        idx = self.rng.choice(n_cells, size=n_food, replace=False)
        for flat in idx:
            r, c = divmod(int(flat), self.cfg.width)
            self.food[r, c] = 1
        # agent starts on empty cell if possible
        empties = np.argwhere(self.food == 0)
        if len(empties) == 0:
            self.x, self.y = 0, 0
        else:
            pick = empties[self.rng.integers(0, len(empties))]
            self.x, self.y = int(pick[0]), int(pick[1])

    def reset(self) -> Observation:
        self.food.fill(0)
        self.energy = self.cfg.energy_start
        self.tick = 0
        self.alive = True
        self.food_collected = 0
        self.invalid_actions = 0
        self.wall_bumps = 0
        self.last_reward = 0.0
        self._place()
        return self.observe()

    def observe(self) -> Observation:
        v = self.cfg.vision
        side = 2 * v + 1
        local = np.zeros((side, side), dtype=np.float32)
        for di in range(-v, v + 1):
            for dj in range(-v, v + 1):
                r, c = self.x + di, self.y + dj
                if 0 <= r < self.cfg.height and 0 <= c < self.cfg.width:
                    local[di + v, dj + v] = float(self.food[r, c])
        return Observation(
            tick=self.tick,
            energy=self.energy,
            energy_max=self.cfg.energy_max,
            x=self.x,
            y=self.y,
            local_food=local.reshape(-1),
            vision=v,
            last_reward=self.last_reward,
            alive=self.alive,
        )

    def step(self, action: Action | int) -> StepResult:
        if not self.alive:
            return StepResult(
                reward=0.0,
                energy=self.energy,
                alive=False,
                food_collected=0,
                invalid_action=True,
                wall_bump=False,
                done=True,
                info={"reason": "already_dead"},
            )

        try:
            act = Action(int(action))
        except ValueError:
            self.invalid_actions += 1
            self.energy = max(0.0, self.energy - self.cfg.drain_rest)
            self.tick += 1
            self.last_reward = -0.25
            done = self._check_done()
            return StepResult(
                reward=self.last_reward,
                energy=self.energy,
                alive=self.alive,
                food_collected=0,
                invalid_action=True,
                wall_bump=False,
                done=done,
            )

        reward = 0.0
        food_got = 0
        wall = False
        invalid = False

        if act in DELTAS:
            dr, dc = DELTAS[act]
            nx, ny = self.x + dr, self.y + dc
            if 0 <= nx < self.cfg.height and 0 <= ny < self.cfg.width:
                self.x, self.y = nx, ny
            else:
                wall = True
                self.wall_bumps += 1
                reward -= 0.05
            self.energy = max(0.0, self.energy - self.cfg.drain_move)
        elif act == Action.FORAGE:
            self.energy = max(0.0, self.energy - self.cfg.drain_rest)
            if self.food[self.x, self.y] == 1:
                self.food[self.x, self.y] = 0
                self.energy = min(self.cfg.energy_max, self.energy + self.cfg.forage_energy)
                self.food_collected += 1
                food_got = 1
                reward += 1.0
            else:
                reward -= 0.05
        elif act == Action.REST:
            self.energy = max(0.0, self.energy - self.cfg.drain_rest)
        elif act == Action.NOOP:
            self.energy = max(0.0, self.energy - self.cfg.drain_rest)
        else:
            invalid = True
            self.invalid_actions += 1
            reward -= 0.25
            self.energy = max(0.0, self.energy - self.cfg.drain_rest)

        self.tick += 1
        self.last_reward = reward
        done = self._check_done()
        return StepResult(
            reward=reward,
            energy=self.energy,
            alive=self.alive,
            food_collected=food_got,
            invalid_action=invalid,
            wall_bump=wall,
            done=done,
            info={},
        )

    def _check_done(self) -> bool:
        if self.energy <= 0:
            self.alive = False
            return True
        if self.tick >= self.cfg.T:
            return True
        return False
