"""
Multi-agent same-map arena for operator Watch (visualization only).

Does NOT change fitness evaluation or the frozen single-agent GridWorld kernel.
Policies see the same Observation contract as solo play (local food + body).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from organism.evaluator import PolicyProtocol
from organism.schemas import ACTION_NAMES, Action, DELTAS, Observation
from organism.world import WorldConfig

# Distinct RGB colors per agent index
AGENT_COLORS: list[np.ndarray] = [
    np.array([255, 214, 10], dtype=np.uint8),   # yellow
    np.array([0, 200, 255], dtype=np.uint8),    # cyan
    np.array([255, 100, 200], dtype=np.uint8),  # pink
    np.array([255, 140, 0], dtype=np.uint8),    # orange
    np.array([180, 130, 255], dtype=np.uint8),  # purple
    np.array([100, 255, 160], dtype=np.uint8),  # mint
]
_EMPTY = np.array([28, 28, 36], dtype=np.uint8)
_FOOD = np.array([46, 160, 67], dtype=np.uint8)
_DEAD = np.array([120, 40, 40], dtype=np.uint8)
_TRAIL = np.array([55, 70, 95], dtype=np.uint8)


@dataclass
class AgentSnapshot:
    genome_id: str
    x: int
    y: int
    energy: float
    food_collected: int
    alive: bool
    action: int | None = None
    reward: float = 0.0

    def action_name(self) -> str:
        if self.action is None:
            return "start"
        try:
            return ACTION_NAMES.get(Action(int(self.action)), str(self.action))
        except Exception:
            return str(self.action)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["action_name"] = self.action_name()
        return d


@dataclass
class MultiFrame:
    tick: int
    food: np.ndarray
    energy_max: float
    agents: list[AgentSnapshot]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "energy_max": self.energy_max,
            "agents": [a.to_dict() for a in self.agents],
            "food_cells": int(np.sum(self.food)),
        }


@dataclass
class MultiReplay:
    frames: list[MultiFrame]
    seed: int
    genome_ids: list[str]
    ablation: str = "Bc"
    error: str = ""
    final: list[dict[str, Any]] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "genome_ids": self.genome_ids,
            "ablation": self.ablation,
            "n_frames": len(self.frames),
            "n_agents": len(self.genome_ids),
            "error": self.error,
            "final": self.final,
        }


@dataclass
class _AgentLive:
    genome_id: str
    policy: PolicyProtocol
    x: int
    y: int
    energy: float
    food_collected: int = 0
    alive: bool = True
    invalid_actions: int = 0
    wall_bumps: int = 0
    last_reward: float = 0.0
    last_action: int | None = None


class MultiAgentArena:
    """Shared food grid + N agent bodies. Host-only visualization."""

    def __init__(self, cfg: WorldConfig, seed: int, n_agents: int) -> None:
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.n_agents = max(1, int(n_agents))
        self.food = np.zeros((cfg.height, cfg.width), dtype=np.int8)
        self.tick = 0
        self.agents: list[_AgentLive] = []

    def place_food_and_agents(
        self,
        policies: list[tuple[str, PolicyProtocol]],
    ) -> None:
        self.food.fill(0)
        self.tick = 0
        n_cells = self.cfg.height * self.cfg.width
        n_food = max(1, int(round(n_cells * self.cfg.food_density)))
        # denser food slightly so multi-agent has something to compete for
        n_food = max(n_food, self.n_agents * 3)
        n_food = min(n_food, n_cells - self.n_agents)
        idx = self.rng.choice(n_cells, size=n_food, replace=False)
        for flat in idx:
            r, c = divmod(int(flat), self.cfg.width)
            self.food[r, c] = 1

        empties = np.argwhere(self.food == 0)
        self.rng.shuffle(empties)
        self.agents = []
        for i, (gid, pol) in enumerate(policies):
            if i < len(empties):
                x, y = int(empties[i][0]), int(empties[i][1])
            else:
                x, y = int(i % self.cfg.height), int(i % self.cfg.width)
            pol.reset(self.seed + i * 17)
            self.agents.append(
                _AgentLive(
                    genome_id=gid,
                    policy=pol,
                    x=x,
                    y=y,
                    energy=float(self.cfg.energy_start),
                )
            )

    def observe(self, agent: _AgentLive) -> Observation:
        v = self.cfg.vision
        side = 2 * v + 1
        local = np.zeros((side, side), dtype=np.float32)
        for di in range(-v, v + 1):
            for dj in range(-v, v + 1):
                r, c = agent.x + di, agent.y + dj
                if 0 <= r < self.cfg.height and 0 <= c < self.cfg.width:
                    local[di + v, dj + v] = float(self.food[r, c])
        return Observation(
            tick=self.tick,
            energy=agent.energy,
            energy_max=self.cfg.energy_max,
            x=agent.x,
            y=agent.y,
            local_food=local.reshape(-1),
            vision=v,
            last_reward=agent.last_reward,
            alive=agent.alive,
        )

    def _apply_action(self, agent: _AgentLive, action: int) -> None:
        if not agent.alive:
            agent.last_action = action
            agent.last_reward = 0.0
            return
        try:
            act = Action(int(action))
        except ValueError:
            agent.invalid_actions += 1
            agent.energy = max(0.0, agent.energy - self.cfg.drain_rest)
            agent.last_reward = -0.25
            agent.last_action = action
            if agent.energy <= 0:
                agent.alive = False
            return

        reward = 0.0
        if act in DELTAS:
            dr, dc = DELTAS[act]
            nx, ny = agent.x + dr, agent.y + dc
            if 0 <= nx < self.cfg.height and 0 <= ny < self.cfg.width:
                agent.x, agent.y = nx, ny
            else:
                agent.wall_bumps += 1
                reward -= 0.05
            agent.energy = max(0.0, agent.energy - self.cfg.drain_move)
        elif act == Action.FORAGE:
            agent.energy = max(0.0, agent.energy - self.cfg.drain_rest)
            if self.food[agent.x, agent.y] == 1:
                self.food[agent.x, agent.y] = 0
                agent.energy = min(
                    self.cfg.energy_max, agent.energy + self.cfg.forage_energy
                )
                agent.food_collected += 1
                reward += 1.0
            else:
                reward -= 0.05
        elif act in (Action.REST, Action.NOOP):
            agent.energy = max(0.0, agent.energy - self.cfg.drain_rest)
        else:
            agent.invalid_actions += 1
            reward -= 0.25
            agent.energy = max(0.0, agent.energy - self.cfg.drain_rest)

        agent.last_reward = reward
        agent.last_action = int(act)
        if agent.energy <= 0:
            agent.alive = False

    def step_round(self) -> MultiFrame:
        """All agents act from simultaneous observations; apply in slot order."""
        actions: list[int] = []
        for ag in self.agents:
            if not ag.alive:
                actions.append(int(Action.NOOP))
                continue
            obs = self.observe(ag)
            try:
                a = ag.policy.act(obs)
                actions.append(int(a))
            except Exception:
                actions.append(int(Action.NOOP))
        for ag, a in zip(self.agents, actions):
            self._apply_action(ag, a)
            try:
                # lightweight step callback if policy expects it
                from organism.schemas import StepResult

                ag.policy.on_step_result(
                    StepResult(
                        reward=ag.last_reward,
                        energy=ag.energy,
                        alive=ag.alive,
                        food_collected=0,
                        invalid_action=False,
                        wall_bump=False,
                        done=not ag.alive,
                    )
                )
            except Exception:
                pass
        self.tick += 1
        return self.snapshot()

    def snapshot(self) -> MultiFrame:
        return MultiFrame(
            tick=int(self.tick),
            food=np.array(self.food, copy=True),
            energy_max=float(self.cfg.energy_max),
            agents=[
                AgentSnapshot(
                    genome_id=ag.genome_id,
                    x=ag.x,
                    y=ag.y,
                    energy=ag.energy,
                    food_collected=ag.food_collected,
                    alive=ag.alive,
                    action=ag.last_action,
                    reward=ag.last_reward,
                )
                for ag in self.agents
            ],
        )

    def done(self) -> bool:
        if self.tick >= self.cfg.T:
            return True
        if all(not ag.alive for ag in self.agents):
            return True
        return False


def multi_frame_to_rgb(
    frame: MultiFrame,
    *,
    cell: int = 18,
    trails: list[set[tuple[int, int]]] | None = None,
) -> np.ndarray:
    h, w = frame.food.shape
    cell = max(2, int(cell))
    img = np.zeros((h * cell, w * cell, 3), dtype=np.uint8)
    agent_cells = {(int(a.x), int(a.y)) for a in frame.agents}

    for i in range(h):
        for j in range(w):
            color = _EMPTY
            if trails:
                for tset in trails:
                    if (i, j) in tset and (i, j) not in agent_cells:
                        color = _TRAIL
                        break
            if frame.food[i, j]:
                color = _FOOD
            img[i * cell : (i + 1) * cell, j * cell : (j + 1) * cell] = color

    for idx, a in enumerate(frame.agents):
        ax, ay = int(a.x), int(a.y)
        if not (0 <= ax < h and 0 <= ay < w):
            continue
        base = AGENT_COLORS[idx % len(AGENT_COLORS)]
        color = base if a.alive else _DEAD
        img[ax * cell : (ax + 1) * cell, ay * cell : (ay + 1) * cell] = color
        # border
        img[ax * cell : (ax + 1) * cell, ay * cell : ay * cell + 1] = 20
        img[ax * cell : (ax + 1) * cell, (ay + 1) * cell - 1 : (ay + 1) * cell] = 20
        img[ax * cell : ax * cell + 1, ay * cell : (ay + 1) * cell] = 20
        img[(ax + 1) * cell - 1 : (ax + 1) * cell, ay * cell : (ay + 1) * cell] = 20
    return img


def trails_up_to(frames: list[MultiFrame], idx: int) -> list[set[tuple[int, int]]]:
    if not frames:
        return []
    n = len(frames[0].agents)
    trails: list[set[tuple[int, int]]] = [set() for _ in range(n)]
    for fr in frames[: max(0, idx) + 1]:
        for i, a in enumerate(fr.agents):
            if i < n:
                trails[i].add((int(a.x), int(a.y)))
    return trails


def record_multi_episode(
    policies: list[tuple[str, PolicyProtocol]],
    world_cfg: WorldConfig,
    seed: int,
    *,
    ablation: str = "Bc",
    episode_timeout_s: float | None = 30.0,
) -> MultiReplay:
    """Run multi-agent episode; return all frames."""
    frames: list[MultiFrame] = []
    err = ""
    arena = MultiAgentArena(world_cfg, seed, n_agents=len(policies))
    deadline = (
        time.monotonic() + float(episode_timeout_s)
        if episode_timeout_s is not None and episode_timeout_s > 0
        else None
    )
    try:
        arena.place_food_and_agents(policies)
        frames.append(arena.snapshot())
        max_steps = max(1, int(world_cfg.T) + 2)
        for _ in range(max_steps):
            if deadline is not None and time.monotonic() >= deadline:
                break
            fr = arena.step_round()
            frames.append(fr)
            if arena.done():
                break
    except Exception as e:
        err = f"{type(e).__name__}: {e}"

    final = [
        {
            "genome_id": ag.genome_id,
            "food_collected": ag.food_collected,
            "energy": ag.energy,
            "alive": ag.alive,
            "ticks": arena.tick,
        }
        for ag in arena.agents
    ] if arena.agents else []

    return MultiReplay(
        frames=frames,
        seed=seed,
        genome_ids=[g for g, _ in policies],
        ablation=ablation,
        error=err,
        final=final,
    )


def iter_multi_episode(
    policies: list[tuple[str, PolicyProtocol]],
    world_cfg: WorldConfig,
    seed: int,
    *,
    episode_timeout_s: float | None = 30.0,
):
    """Yield MultiFrame as the multi-agent episode runs."""
    arena = MultiAgentArena(world_cfg, seed, n_agents=len(policies))
    deadline = (
        time.monotonic() + float(episode_timeout_s)
        if episode_timeout_s is not None and episode_timeout_s > 0
        else None
    )
    try:
        arena.place_food_and_agents(policies)
        yield arena.snapshot(), False, ""
        max_steps = max(1, int(world_cfg.T) + 2)
        for _ in range(max_steps):
            if deadline is not None and time.monotonic() >= deadline:
                yield arena.snapshot(), True, "timeout_wall"
                return
            fr = arena.step_round()
            done = arena.done()
            yield fr, done, ""
            if done:
                return
    except Exception as e:
        yield arena.snapshot() if arena.agents else MultiFrame(
            tick=0,
            food=np.zeros((world_cfg.height, world_cfg.width), dtype=np.int8),
            energy_max=world_cfg.energy_max,
            agents=[],
        ), True, f"{type(e).__name__}: {e}"


def multi_replay_to_gif(
    replay: MultiReplay,
    path: str | Path,
    *,
    cell: int = 14,
    duration_ms: int = 80,
    show_trail: bool = True,
) -> Path:
    from PIL import Image

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for i, fr in enumerate(replay.frames):
        trails = trails_up_to(replay.frames, i) if show_trail else None
        rgb = multi_frame_to_rgb(fr, cell=cell, trails=trails)
        images.append(Image.fromarray(rgb, mode="RGB"))
    if not images:
        raise ValueError("no frames")
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
    )
    return path
