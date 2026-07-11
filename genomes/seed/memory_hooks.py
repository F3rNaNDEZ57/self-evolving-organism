"""Optional experience hooks for the seed genome."""

from __future__ import annotations

from organism.schemas import StepResult


class SimpleMemory:
    def __init__(self) -> None:
        self.steps = 0
        self.total_reward = 0.0
        self.food_events = 0

    def reset(self) -> None:
        self.steps = 0
        self.total_reward = 0.0
        self.food_events = 0

    def on_step(self, result: StepResult) -> None:
        self.steps += 1
        self.total_reward += float(result.reward)
        self.food_events += int(result.food_collected)

    def summary(self) -> dict:
        return {
            "steps": self.steps,
            "total_reward": self.total_reward,
            "food_events": self.food_events,
        }
