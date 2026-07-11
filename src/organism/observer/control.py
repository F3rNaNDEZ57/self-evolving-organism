"""Operator control plane: pause / freeze genomic mutations (UI kill switch)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class ControlState:
    """Written by the observer UI; read by mutate/evolve before genomic work."""

    mutations_paused: bool = False
    frozen: bool = False  # hard freeze — no mutate/evolve mutations
    note: str = ""
    updated_at: float = 0.0
    updated_by: str = "operator"

    def mutations_allowed(self) -> bool:
        return not self.mutations_paused and not self.frozen

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ControlState:
        return cls(
            mutations_paused=bool(d.get("mutations_paused", False)),
            frozen=bool(d.get("frozen", False)),
            note=str(d.get("note") or ""),
            updated_at=float(d.get("updated_at") or 0.0),
            updated_by=str(d.get("updated_by") or "operator"),
        )


def control_path(artifacts_dir: Path) -> Path:
    return Path(artifacts_dir) / "control.json"


def load_control(artifacts_dir: Path) -> ControlState:
    p = control_path(artifacts_dir)
    if not p.exists():
        return ControlState()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return ControlState.from_dict(data if isinstance(data, dict) else {})
    except Exception:
        return ControlState()


def save_control(artifacts_dir: Path, state: ControlState) -> Path:
    p = control_path(artifacts_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = time.time()
    p.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return p


def mutations_allowed(artifacts_dir: Path) -> tuple[bool, str]:
    """Return (ok, reason). Used by CLI mutate/evolve before genomic work."""
    st = load_control(artifacts_dir)
    if st.frozen:
        return False, f"mutations frozen by operator ({st.note or 'no note'})"
    if st.mutations_paused:
        return False, f"mutations paused by operator ({st.note or 'no note'})"
    return True, ""
