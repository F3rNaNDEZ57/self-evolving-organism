"""
Episode recording + RGB frames for the operator Watch surface.

Host-only visualization path — not the organism brain, not used for fitness claims.
Mirrors run_episode but snapshots grid state each step.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from organism.evaluator import PolicyProtocol, episode_score, FitnessConfig
from organism.schemas import ACTION_NAMES, Action, EpisodeSummary
from organism.world import GridWorld, WorldConfig


@dataclass
class Frame:
    tick: int
    x: int
    y: int
    energy: float
    energy_max: float
    food: np.ndarray  # int8 HxW copy
    action: int | None  # None = initial frame before first act
    reward: float
    food_collected: int
    alive: bool
    wall_bump: bool = False
    invalid: bool = False

    def action_name(self) -> str:
        if self.action is None:
            return "start"
        try:
            return ACTION_NAMES.get(Action(int(self.action)), str(self.action))
        except Exception:
            return str(self.action)


@dataclass
class EpisodeReplay:
    frames: list[Frame]
    summary: EpisodeSummary
    seed: int
    genome_id: str = ""
    ablation: str = "Bc"
    error: str = ""

    def to_meta(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "genome_id": self.genome_id,
            "ablation": self.ablation,
            "n_frames": len(self.frames),
            "error": self.error,
            "summary": {
                "score": self.summary.score,
                "food_collected": self.summary.food_collected,
                "ticks_survived": self.summary.ticks_survived,
                "final_energy": self.summary.final_energy,
                "invalid_actions": self.summary.invalid_actions,
                "wall_bumps": self.summary.wall_bumps,
                "death_reason": self.summary.death_reason,
            },
        }


def _snapshot(
    world: GridWorld,
    *,
    action: int | None,
    reward: float = 0.0,
    wall_bump: bool = False,
    invalid: bool = False,
) -> Frame:
    return Frame(
        tick=int(world.tick),
        x=int(world.x),
        y=int(world.y),
        energy=float(world.energy),
        energy_max=float(world.cfg.energy_max),
        food=np.array(world.food, copy=True),
        action=action,
        reward=float(reward),
        food_collected=int(world.food_collected),
        alive=bool(world.alive),
        wall_bump=wall_bump,
        invalid=invalid,
    )


def record_episode(
    policy: PolicyProtocol,
    world_cfg: WorldConfig,
    seed: int,
    *,
    train_weights: bool = False,
    episode_timeout_s: float | None = None,
    genome_id: str = "",
    ablation: str = "Bc",
    fit_cfg: FitnessConfig | None = None,
) -> EpisodeReplay:
    """
    Run one host episode and capture a Frame after reset and after each step.
    On policy crash: return frames so far with error set.
    """
    world = GridWorld(world_cfg, seed=seed)
    frames: list[Frame] = []
    death = "timeout"
    err = ""
    deadline = (
        time.monotonic() + float(episode_timeout_s)
        if episode_timeout_s is not None and episode_timeout_s > 0
        else None
    )
    max_steps = max(1, int(world_cfg.T) + 5)

    try:
        obs = world.reset()
        policy.reset(seed)
        frames.append(_snapshot(world, action=None))
        steps = 0
        while steps < max_steps:
            if deadline is not None and time.monotonic() >= deadline:
                death = "timeout_wall"
                break
            action = policy.act(obs)
            result = world.step(action)
            steps += 1
            try:
                if train_weights:
                    policy.on_step_result(result)
                else:
                    policy.on_step_result(result)
            except Exception:
                pass
            frames.append(
                _snapshot(
                    world,
                    action=int(action),
                    reward=float(result.reward),
                    wall_bump=bool(result.wall_bump),
                    invalid=bool(result.invalid_action),
                )
            )
            if result.done:
                if death == "timeout_wall":
                    break
                if not result.alive or world.energy <= 0:
                    death = "energy"
                break
            obs = world.observe()
            if deadline is not None and time.monotonic() >= deadline:
                death = "timeout_wall"
                break
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if not frames:
            # still try empty world snapshot for UI
            try:
                frames.append(_snapshot(world, action=None))
            except Exception:
                pass

    summary = EpisodeSummary(
        seed=seed,
        score=0.0,
        food_collected=world.food_collected if death != "timeout_wall" else 0,
        ticks_survived=world.tick,
        final_energy=world.energy if death != "timeout_wall" else 0.0,
        invalid_actions=world.invalid_actions,
        wall_bumps=world.wall_bumps,
        death_reason=death if not err else "error",
    )
    if fit_cfg is not None and not err:
        summary.score = episode_score(summary, fit_cfg)

    return EpisodeReplay(
        frames=frames,
        summary=summary,
        seed=seed,
        genome_id=genome_id,
        ablation=ablation,
        error=err,
    )


# BGR-ish palette as RGB uint8
_EMPTY = np.array([28, 28, 36], dtype=np.uint8)
_FOOD = np.array([46, 160, 67], dtype=np.uint8)
_AGENT = np.array([255, 214, 10], dtype=np.uint8)
_TRAIL = np.array([70, 90, 120], dtype=np.uint8)
_DEAD = np.array([200, 60, 60], dtype=np.uint8)


def frame_to_rgb(
    frame: Frame,
    *,
    cell: int = 18,
    trail: set[tuple[int, int]] | None = None,
) -> np.ndarray:
    """Upscale grid to HxWx3 uint8 image."""
    h, w = frame.food.shape
    cell = max(2, int(cell))
    img = np.zeros((h * cell, w * cell, 3), dtype=np.uint8)
    for i in range(h):
        for j in range(w):
            if trail and (i, j) in trail and not (i == frame.x and j == frame.y):
                color = _TRAIL
            elif frame.food[i, j]:
                color = _FOOD
            else:
                color = _EMPTY
            img[i * cell : (i + 1) * cell, j * cell : (j + 1) * cell] = color
    # agent cell
    ax, ay = int(frame.x), int(frame.y)
    if 0 <= ax < h and 0 <= ay < w:
        color = _AGENT if frame.alive else _DEAD
        img[ax * cell : (ax + 1) * cell, ay * cell : (ay + 1) * cell] = color
        # small border
        img[ax * cell : (ax + 1) * cell, ay * cell : ay * cell + 1] = 20
        img[ax * cell : (ax + 1) * cell, (ay + 1) * cell - 1 : (ay + 1) * cell] = 20
        img[ax * cell : ax * cell + 1, ay * cell : (ay + 1) * cell] = 20
        img[(ax + 1) * cell - 1 : (ax + 1) * cell, ay * cell : (ay + 1) * cell] = 20
    return img


def trail_up_to(frames: list[Frame], idx: int) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for f in frames[: max(0, idx) + 1]:
        out.add((int(f.x), int(f.y)))
    return out


def replay_to_gif(
    replay: EpisodeReplay,
    path: str | Path,
    *,
    cell: int = 14,
    duration_ms: int = 80,
    show_trail: bool = True,
) -> Path:
    """Write animated GIF via Pillow."""
    from PIL import Image

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for i, fr in enumerate(replay.frames):
        trail = trail_up_to(replay.frames, i) if show_trail else None
        rgb = frame_to_rgb(fr, cell=cell, trail=trail)
        images.append(Image.fromarray(rgb, mode="RGB"))
    if not images:
        raise ValueError("no frames to write")
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
    )
    return path
