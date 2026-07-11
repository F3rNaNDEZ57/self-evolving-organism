"""Mediocre seed heuristics — intentionally weak so mutation has room."""

from __future__ import annotations

from organism.schemas import Action, Observation


def nearest_food_direction(obs: Observation) -> Action | None:
    """Return a move toward nearest visible food, or None if none seen."""
    v = obs.vision
    side = 2 * v + 1
    grid = obs.local_food.reshape(side, side)
    best = None
    best_d = 10**9
    for i in range(side):
        for j in range(side):
            if grid[i, j] <= 0:
                continue
            di, dj = i - v, j - v
            dist = abs(di) + abs(dj)
            if dist < best_d:
                best_d = dist
                best = (di, dj)
    if best is None or best_d == 0:
        return None
    di, dj = best
    if abs(di) >= abs(dj):
        return Action.S if di > 0 else Action.N
    return Action.E if dj > 0 else Action.W


def should_forage(obs: Observation) -> bool:
    v = obs.vision
    side = 2 * v + 1
    grid = obs.local_food.reshape(side, side)
    return float(grid[v, v]) > 0
