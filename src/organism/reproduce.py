"""
Phase 6: package a reproduce bundle (config + last reports, no secrets).
"""

from __future__ import annotations

import json
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from organism.config import ROOT


REPORT_GLOBS = (
    "last_*.json",
    "last_doctor_report.json",
    "active_genome.json",
    "control.json",
)


@dataclass
class PackageResult:
    package_id: str
    dir_path: str
    zip_path: str
    files: list[str]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_copy(src: Path, dest: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def package_reproduce(
    artifacts_dir: Path,
    *,
    out_root: Path | None = None,
    include_zip: bool = True,
) -> PackageResult:
    """
    Copy non-secret config + last machine reports into artifacts/packages/{id}/.
    """
    artifacts_dir = Path(artifacts_dir)
    package_id = f"pkg_{int(time.time())}"
    root = Path(out_root) if out_root else artifacts_dir / "packages"
    pkg = root / package_id
    pkg.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    # Config (no .env)
    for rel in (
        "config/experiment_v0.prereg.yaml",
        "config/nim.pinned.yaml",
    ):
        src = ROOT / rel
        if _safe_copy(src, pkg / rel.replace("/", "_")):
            copied.append(rel)

    # Strip api keys from nim copy if any leaked into yaml (defensive)
    nim_copy = pkg / "config_nim.pinned.yaml"
    if nim_copy.exists():
        try:
            text = nim_copy.read_text(encoding="utf-8")
            # do not strip model pins; keys should not be in yaml
            if "api_key" in text.lower() or "nvapi-" in text:
                lines = [
                    ln
                    for ln in text.splitlines()
                    if "api_key" not in ln.lower() and "nvapi-" not in ln
                ]
                nim_copy.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    for pattern in REPORT_GLOBS:
        for src in artifacts_dir.glob(pattern):
            if src.is_file() and _safe_copy(src, pkg / "reports" / src.name):
                copied.append(f"artifacts/{src.name}")

    # Elites registry (paths only)
    elites = artifacts_dir / "elites" / "registry.json"
    if _safe_copy(elites, pkg / "reports" / "elites_registry.json"):
        copied.append("artifacts/elites/registry.json")

    # Latest weights meta only (not .npz tensors — keep bundle small)
    wlatest = artifacts_dir / "weights" / "latest.json"
    if _safe_copy(wlatest, pkg / "reports" / "weights_latest.json"):
        copied.append("artifacts/weights/latest.json")

    readme = pkg / "REPRODUCE.md"
    readme.write_text(
        f"""# Reproduce package `{package_id}`

Created: {time.strftime("%Y-%m-%d %H:%M:%S")}

## Contents
Machine reports + pinned configs (no `.env` / API keys).

## Commands (from repo root)

```powershell
# health
seo doctor

# optional: restore awareness of last diagnose
# (copy reports/* into artifacts/ if you want)

# code-first mutate (safety rail applies)
seo mutate --dry-run --ablation Bc --critic

# weights check (do not load if diagnose negative)
seo weights diagnose --weights latest

# multi-lineage dry evolve
seo evolve --dry-run --cycles 3 --lineages 2 --select fitness_rank

# export lab note
seo runs export --kind auto
```

## Notes
- Genome code snapshots are **not** fully included (use git + artifacts/genomes separately).
- Live NIM requires local `.env` with `NVIDIA_API_KEY`.
- Files: {len(copied)} copied.
""",
        encoding="utf-8",
    )
    copied.append("REPRODUCE.md")

    manifest = {
        "package_id": package_id,
        "created_at": time.time(),
        "files": copied,
        "root": str(ROOT),
    }
    (pkg / "package_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    zip_path = ""
    if include_zip:
        zpath = root / f"{package_id}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in pkg.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=str(f.relative_to(pkg)))
        zip_path = str(zpath)

    return PackageResult(
        package_id=package_id,
        dir_path=str(pkg),
        zip_path=zip_path,
        files=copied,
        created_at=time.time(),
    )
