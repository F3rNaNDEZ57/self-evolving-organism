"""SQLite lineage + metrics store."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS genomes (
              id TEXT PRIMARY KEY,
              parent_id TEXT,
              status TEXT,
              ablation TEXT,
              artifact_path TEXT,
              created_at REAL
            );
            CREATE TABLE IF NOT EXISTS evaluations (
              id TEXT PRIMARY KEY,
              genome_id TEXT,
              fitness REAL,
              mean_score REAL,
              std_score REAL,
              seeds_json TEXT,
              metrics_json TEXT,
              created_at REAL
            );
            CREATE TABLE IF NOT EXISTS episodes (
              id TEXT PRIMARY KEY,
              evaluation_id TEXT,
              genome_id TEXT,
              seed INTEGER,
              score REAL,
              summary_json TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY,
              ts REAL,
              type TEXT,
              payload_json TEXT
            );
            CREATE TABLE IF NOT EXISTS mutations (
              id TEXT PRIMARY KEY,
              parent_genome_id TEXT,
              candidate_genome_id TEXT,
              decision TEXT,
              reason TEXT,
              meta_json TEXT,
              created_at REAL
            );
            CREATE TABLE IF NOT EXISTS weight_checkpoints (
              id TEXT PRIMARY KEY,
              genome_id TEXT,
              path TEXT,
              sha256 TEXT,
              feature_dim INTEGER,
              train_fitness REAL,
              holdout_fitness REAL,
              ablation TEXT,
              episodes_trained INTEGER,
              label TEXT,
              meta_json TEXT,
              created_at REAL
            );
            CREATE TABLE IF NOT EXISTS llm_calls (
              id TEXT PRIMARY KEY,
              mutation_id TEXT,
              role TEXT,
              model TEXT,
              tokens_in INTEGER,
              tokens_out INTEGER,
              estimated_usd REAL,
              latency_ms REAL,
              meta_json TEXT,
              created_at REAL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def log_event(self, event_type: str, payload: dict[str, Any]) -> str:
        eid = _uid()
        self.conn.execute(
            "INSERT INTO events (id, ts, type, payload_json) VALUES (?,?,?,?)",
            (eid, time.time(), event_type, json.dumps(payload)),
        )
        self.conn.commit()
        return eid

    def insert_genome(
        self,
        genome_id: str | None = None,
        parent_id: str | None = None,
        status: str = "active",
        ablation: str = "B0",
        artifact_path: str = "",
    ) -> str:
        gid = genome_id or f"g_{_uid()}"
        self.conn.execute(
            """
            INSERT INTO genomes (id, parent_id, status, ablation, artifact_path, created_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              parent_id=excluded.parent_id,
              status=excluded.status,
              ablation=excluded.ablation,
              artifact_path=excluded.artifact_path
            """,
            (gid, parent_id, status, ablation, artifact_path, time.time()),
        )
        self.conn.commit()
        return gid

    def insert_evaluation(
        self,
        genome_id: str,
        fitness: float,
        mean_score: float,
        std_score: float,
        seeds: list[int],
        episodes: list[Any],
    ) -> str:
        eid = f"e_{_uid()}"
        self.conn.execute(
            "INSERT INTO evaluations (id, genome_id, fitness, mean_score, std_score, seeds_json, metrics_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                eid,
                genome_id,
                fitness,
                mean_score,
                std_score,
                json.dumps(seeds),
                json.dumps({"n": len(episodes)}),
                time.time(),
            ),
        )
        for ep in episodes:
            data = asdict(ep) if hasattr(ep, "__dataclass_fields__") else dict(ep)
            self.conn.execute(
                "INSERT INTO episodes (id, evaluation_id, genome_id, seed, score, summary_json) VALUES (?,?,?,?,?,?)",
                (f"ep_{_uid()}", eid, genome_id, data.get("seed"), data.get("score"), json.dumps(data)),
            )
        self.conn.commit()
        return eid

    def insert_mutation(
        self,
        mutation_id: str,
        parent_genome_id: str,
        candidate_genome_id: str,
        decision: str,
        reason: str,
        meta: dict[str, Any] | None = None,
    ) -> str:
        self.conn.execute(
            "INSERT INTO mutations (id, parent_genome_id, candidate_genome_id, decision, reason, meta_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                mutation_id,
                parent_genome_id,
                candidate_genome_id,
                decision,
                reason,
                json.dumps(meta or {}),
                time.time(),
            ),
        )
        self.conn.commit()
        return mutation_id

    def set_genome_status(self, genome_id: str, status: str) -> None:
        self.conn.execute("UPDATE genomes SET status=? WHERE id=?", (status, genome_id))
        self.conn.commit()

    def get_genome(self, genome_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM genomes WHERE id=?", (genome_id,)).fetchone()
        return dict(row) if row else None

    def insert_weight_checkpoint(
        self,
        checkpoint_id: str,
        genome_id: str,
        path: str,
        sha256: str,
        feature_dim: int,
        *,
        train_fitness: float | None = None,
        holdout_fitness: float | None = None,
        ablation: str = "Bw",
        episodes_trained: int = 0,
        label: str = "",
        meta: dict[str, Any] | None = None,
    ) -> str:
        self.conn.execute(
            """
            INSERT INTO weight_checkpoints
              (id, genome_id, path, sha256, feature_dim, train_fitness, holdout_fitness,
               ablation, episodes_trained, label, meta_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              path=excluded.path,
              sha256=excluded.sha256,
              train_fitness=excluded.train_fitness,
              holdout_fitness=excluded.holdout_fitness,
              label=excluded.label,
              meta_json=excluded.meta_json
            """,
            (
                checkpoint_id,
                genome_id,
                path,
                sha256,
                feature_dim,
                train_fitness,
                holdout_fitness,
                ablation,
                episodes_trained,
                label,
                json.dumps(meta or {}),
                time.time(),
            ),
        )
        self.conn.commit()
        return checkpoint_id

    def list_weight_checkpoints(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM weight_checkpoints ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_llm_call(
        self,
        *,
        model: str,
        role: str = "",
        mutation_id: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        estimated_usd: float = 0.0,
        latency_ms: float = 0.0,
        meta: dict[str, Any] | None = None,
    ) -> str:
        cid = f"llm_{_uid()}"
        self.conn.execute(
            """
            INSERT INTO llm_calls
              (id, mutation_id, role, model, tokens_in, tokens_out,
               estimated_usd, latency_ms, meta_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cid,
                mutation_id,
                role,
                model,
                tokens_in,
                tokens_out,
                estimated_usd,
                latency_ms,
                json.dumps(meta or {}),
                time.time(),
            ),
        )
        self.conn.commit()
        return cid

    def llm_usage_for_mutation(self, mutation_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT * FROM llm_calls WHERE mutation_id=?",
            (mutation_id,),
        ).fetchall()
        tokens_in = sum(int(r["tokens_in"] or 0) for r in rows)
        tokens_out = sum(int(r["tokens_out"] or 0) for r in rows)
        latency = sum(float(r["latency_ms"] or 0) for r in rows)
        return {
            "calls": len(rows),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "latency_ms": latency,
            "estimated_usd": sum(float(r["estimated_usd"] or 0) for r in rows),
        }

    def cost_per_accepted_gain(
        self,
        *,
        parent_fitness: float,
        candidate_fitness: float,
        tokens_total: int,
    ) -> float | None:
        """Tokens per unit fitness gain (free endpoints: usd=0). None if no gain."""
        gain = float(candidate_fitness) - float(parent_fitness)
        if gain <= 0:
            return None
        return float(tokens_total) / gain
