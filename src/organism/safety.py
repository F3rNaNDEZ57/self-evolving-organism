"""
Operator safety rails based on last weights diagnose.

When diagnose says do not use weights, prefer Bc over Bcw for mutations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_weights_diagnose(artifacts_dir: Path) -> dict[str, Any] | None:
    p = Path(artifacts_dir) / "last_weights_diagnose.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def weights_preferred(artifacts_dir: Path) -> tuple[bool, str]:
    """
    Return (prefer_weights, reason).
    Missing diagnose → False (code-only safety default).
    """
    d = load_weights_diagnose(artifacts_dir)
    if not d:
        return (
            False,
            "no last_weights_diagnose.json — default code-only (Bc); "
            "run: seo weights diagnose --weights latest",
        )
    use = bool(d.get("recommend_use_weights"))
    rec = str(d.get("recommendation") or "")
    if use:
        return True, rec or "diagnose recommends using weights"
    return False, rec or "diagnose recommends against weights"


def recommend_mutation_ablation(
    artifacts_dir: Path,
    requested: str,
    *,
    force_weights: bool = False,
) -> tuple[str, str, bool]:
    """
    Map requested ablation through safety rail.

    Returns (effective_ablation, reason, downgraded).
    """
    req = (requested or "Bc").strip()
    if req not in ("Bc", "Bcw", "B0", "Bw"):
        req = "Bc"
    # Code-only ablations always fine
    if req in ("Bc", "B0"):
        return req, "code-only ablation", False
    # Weight ablations
    if force_weights:
        return req, "force_weights=True — safety rail skipped", False
    prefer, why = weights_preferred(artifacts_dir)
    if prefer:
        return req, why, False
    # Downgrade Bw/Bcw → Bc (or B0 if they asked Bw-only without code)
    safe = "Bc" if req == "Bcw" else "Bc"
    if req == "Bw":
        safe = "Bc"  # still code path for genomic mutate CLI; Bw alone is rare for mutate
    return (
        safe,
        f"safety rail: requested {req} but weights not preferred — using {safe}. ({why})",
        True,
    )
