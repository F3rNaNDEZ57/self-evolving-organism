"""
Export machine reports → Obsidian Runs/ lab notes.

Operator helper — does not change science. Writes markdown under
self-evolving-organism-docs/Runs/ (or custom vault path).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from organism.config import ROOT

ReportKind = Literal["auto", "evolve", "ablate", "mutation", "population"]

KIND_FILES: dict[str, str] = {
    "evolve": "last_evolve_report.json",
    "population": "last_evolve_report.json",
    "ablate": "last_ablation_report.json",
    "mutation": "last_mutation_result.json",
}


@dataclass
class ExportResult:
    kind: str
    path: Path
    title: str
    run_id: str
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "title": self.title,
            "run_id": self.run_id,
            "created": self.created,
        }


def default_vault_runs_dir() -> Path:
    return ROOT / "self-evolving-organism-docs" / "Runs"


def load_report(artifacts_dir: Path, kind: str) -> tuple[str, dict[str, Any], Path]:
    """Return (resolved_kind, data, source_path)."""
    artifacts_dir = Path(artifacts_dir)
    k = (kind or "auto").lower().strip()
    if k == "auto":
        # Prefer newest among available last_* reports
        candidates: list[tuple[float, str, Path]] = []
        for name, fname in (
            ("evolve", "last_evolve_report.json"),
            ("ablate", "last_ablation_report.json"),
            ("mutation", "last_mutation_result.json"),
        ):
            p = artifacts_dir / fname
            if p.exists():
                candidates.append((p.stat().st_mtime, name, p))
        if not candidates:
            raise FileNotFoundError(
                f"No last_* reports under {artifacts_dir} "
                "(run evolve / ablate / mutate first)"
            )
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, k, path = candidates[0]
    else:
        if k == "population":
            k = "evolve"
        fname = KIND_FILES.get(k)
        if not fname:
            raise ValueError(f"unknown kind {kind!r}; use auto|evolve|ablate|mutation")
        path = artifacts_dir / fname
        if not path.exists():
            raise FileNotFoundError(f"missing report: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report is not a JSON object: {path}")

    # Population evolve reports include lineages
    if k == "evolve" and data.get("lineages"):
        k = "population"

    return k, data, path


def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:48] or "run"


def _fmt_f(x: Any, digits: int = 4) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except Exception:
        return "—"


def render_evolve_note(
    data: dict[str, Any],
    *,
    source: Path,
    day: str,
    title: str | None = None,
) -> tuple[str, str, str]:
    run_id = str(data.get("run_id") or "evolve")
    lineages = data.get("lineages") or []
    is_pop = bool(lineages) or int(data.get("max_lineages") or 1) > 1
    kind = "population" if is_pop else "evolve"
    slug = _slugify(f"{day}-{kind}-{run_id}")
    ttl = title or (
        f"Population evolve {run_id}" if is_pop else f"Evolve {run_id}"
    )
    hist = data.get("fitness_history") or []
    f0 = _fmt_f(hist[0]) if hist else "—"
    f1 = _fmt_f(hist[-1]) if hist else "—"
    fbest = _fmt_f(max(hist)) if hist else "—"
    events = data.get("events") or []
    mut_kinds = [
        e.get("kind")
        for e in events
        if isinstance(e, dict) and str(e.get("kind", "")).startswith("mutate")
    ]
    select_events = [
        e for e in events if isinstance(e, dict) and e.get("kind") == "select"
    ]

    lines = [
        "---",
        f"title: {ttl}",
        "tags:",
        "  - run",
        f"  - phase/5",
        f"  - {kind}",
        f"run_id: {run_id}",
        f"status: complete",
        f"updated: {day}",
        f"source: {source.as_posix()}",
        "---",
        "",
        f"# {ttl}",
        "",
        "## Summary",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| run_id | `{run_id}` |",
        f"| ablation | {data.get('ablation')} |",
        f"| dry_run | {data.get('dry_run')} |",
        f"| episodes_run | {data.get('episodes_run')} |",
        f"| mutations | acc={data.get('mutations_accepted')} / "
        f"rej={data.get('mutations_rejected')} / "
        f"fail={data.get('mutations_failed')} / "
        f"att={data.get('mutations_attempted')} |",
        f"| start_genome | `{data.get('start_genome_id')}` |",
        f"| final_genome | `{data.get('final_genome_id')}` |",
        f"| fitness first → last | {f0} → {f1} |",
        f"| fitness best | {fbest} |",
        f"| max_lineages | {data.get('max_lineages', 1)} |",
        f"| lineage_schedule | {data.get('lineage_schedule', '—')} |",
        "",
        "## Fitness history",
        "",
        "```",
        ", ".join(_fmt_f(x, 3) for x in hist[:40])
        + (" …" if len(hist) > 40 else ""),
        "```",
        "",
    ]

    if lineages:
        lines += [
            "## Lineage slots",
            "",
            "| slot | genome | fitness | evals | mut att | exhausted |",
            "|------|--------|---------|-------|---------|-----------|",
        ]
        for lin in lineages:
            if not isinstance(lin, dict):
                continue
            lines.append(
                f"| {lin.get('slot_id')} | `{lin.get('genome_id')}` | "
                f"{_fmt_f(lin.get('fitness'))} | {lin.get('eval_cycles')} | "
                f"{lin.get('mutations_attempted')} | {lin.get('exhausted')} |"
            )
        lines.append("")

    if select_events:
        lines += ["## Selection events", ""]
        for e in select_events[:12]:
            lines.append(
                f"- `{e.get('genome_id')}` — {e.get('reason')}"
            )
        lines.append("")

    lines += [
        "## Mutation triggers",
        "",
        ", ".join(str(k) for k in mut_kinds) if mut_kinds else "_(none)_",
        "",
        "## Operator notes",
        "",
        "_Fill in: what you intended, what surprised you, next experiment._",
        "",
        "## Source",
        "",
        f"- Report: `{source}`",
        f"- Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "→ [[Runs/README|Runs index]] · [[Phase 5 Population]] · [[System Map]]",
        "",
    ]
    return kind, slug, "\n".join(lines)


def render_ablate_note(
    data: dict[str, Any],
    *,
    source: Path,
    day: str,
    title: str | None = None,
) -> tuple[str, str, str]:
    run_id = str(data.get("run_id") or "ablate")
    slug = _slugify(f"{day}-ablate-{run_id}")
    ttl = title or f"Ablation {run_id}"
    delta = data.get("delta_holdout_bcw_minus_b0")
    thr = data.get("delta_success")
    success = data.get("success")
    arms = data.get("arms") or data.get("arm_results") or []

    lines = [
        "---",
        f"title: {ttl}",
        "tags:",
        "  - run",
        "  - ablation",
        f"run_id: {run_id}",
        f"status: complete",
        f"updated: {day}",
        f"source: {source.as_posix()}",
        "---",
        "",
        f"# {ttl}",
        "",
        "## Holdout δ",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Bcw − B0 | {_fmt_f(delta)} |",
        f"| δ threshold | {_fmt_f(thr)} |",
        f"| success | **{success}** |",
        f"| dry_run | {data.get('dry_run')} |",
        "",
    ]

    if isinstance(arms, list) and arms:
        lines += [
            "## Arms",
            "",
            "| arm | holdout | notes |",
            "|-----|---------|-------|",
        ]
        for a in arms:
            if isinstance(a, dict):
                lines.append(
                    f"| {a.get('name') or a.get('arm')} | "
                    f"{_fmt_f(a.get('holdout_fitness') or a.get('fitness'))} | "
                    f"{str(a.get('notes') or '')[:40]} |"
                )
            else:
                lines.append(f"| {a} | — | |")
        lines.append("")

    comps = data.get("comparisons") or {}
    if isinstance(comps, dict) and comps:
        lines += ["## Comparisons", ""]
        for k, v in comps.items():
            lines.append(f"- `{k}`: {_fmt_f(v)}")
        lines.append("")

    lines += [
        "## Operator notes",
        "",
        "_Fill in interpretation and next steps._",
        "",
        "## Source",
        "",
        f"- Report: `{source}`",
        f"- Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "→ [[Runs/README|Runs index]] · [[System Map]]",
        "",
    ]
    return "ablate", slug, "\n".join(lines)


def render_mutation_note(
    data: dict[str, Any],
    *,
    source: Path,
    day: str,
    title: str | None = None,
) -> tuple[str, str, str]:
    mid = str(data.get("mutation_id") or "mutation")
    slug = _slugify(f"{day}-mutate-{mid}")
    ttl = title or f"Mutation {mid}"
    lines = [
        "---",
        f"title: {ttl}",
        "tags:",
        "  - run",
        "  - mutation",
        f"run_id: {mid}",
        f"status: complete",
        f"updated: {day}",
        f"source: {source.as_posix()}",
        "---",
        "",
        f"# {ttl}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| decision | **{data.get('decision')}** |",
        f"| reason | {data.get('reason')} |",
        f"| parent | `{data.get('parent_genome_id') or data.get('parent_id')}` |",
        f"| candidate | `{data.get('candidate_genome_id')}` |",
        f"| parent_fitness | {_fmt_f(data.get('parent_fitness'))} |",
        f"| candidate_fitness | {_fmt_f(data.get('candidate_fitness'))} |",
        f"| epsilon | {_fmt_f(data.get('epsilon'))} |",
        f"| critic | {data.get('critic_decision')} [{data.get('critic_code')}] |",
        f"| model | {data.get('model')} |",
        "",
        f"**Rationale:** {data.get('rationale') or '—'}",
        "",
        "## Operator notes",
        "",
        "_Fill in._",
        "",
        f"- Source: `{source}`",
        "",
        "→ [[Runs/README|Runs index]] · [[Mutations/README|Mutations]]",
        "",
    ]
    return "mutation", slug, "\n".join(lines)


def render_note(
    kind: str,
    data: dict[str, Any],
    *,
    source: Path,
    day: str | None = None,
    title: str | None = None,
) -> tuple[str, str, str]:
    day = day or date.today().isoformat()
    if kind in ("evolve", "population"):
        return render_evolve_note(data, source=source, day=day, title=title)
    if kind == "ablate":
        return render_ablate_note(data, source=source, day=day, title=title)
    if kind == "mutation":
        return render_mutation_note(data, source=source, day=day, title=title)
    raise ValueError(f"cannot render kind={kind}")


def append_runs_index(runs_dir: Path, *, day: str, slug: str, title: str, kind: str) -> None:
    """Best-effort append a row to Runs/README.md index table."""
    readme = runs_dir / "README.md"
    if not readme.exists():
        return
    text = readme.read_text(encoding="utf-8")
    if slug in text:
        return
    row = f"| {day} | [[{slug}]] | {kind} | auto-export: {title[:40]} |"
    lines = text.splitlines()
    # Find markdown table separator under ## Index and insert row after last table row
    idx_header = None
    for i, line in enumerate(lines):
        if line.strip().startswith("| Date |") or (
            "| Date |" in line and "Note" in line
        ):
            idx_header = i
            break
    if idx_header is None:
        readme.write_text(text.rstrip() + "\n\n" + row + "\n", encoding="utf-8")
        return
    # skip separator
    j = idx_header + 1
    if j < len(lines) and re.match(r"^\|\s*[-:]+", lines[j].strip()):
        j += 1
    while j < len(lines) and lines[j].strip().startswith("|"):
        j += 1
    lines.insert(j, row)
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_run_note(
    artifacts_dir: Path,
    *,
    kind: str = "auto",
    vault_runs: Path | None = None,
    title: str | None = None,
    slug: str | None = None,
    update_index: bool = True,
    force: bool = False,
) -> ExportResult:
    """
    Load last report of kind, write Runs/YYYY-MM-DD-….md markdown note.
    """
    artifacts_dir = Path(artifacts_dir)
    resolved, data, source = load_report(artifacts_dir, kind)
    day = date.today().isoformat()
    rkind, auto_slug, body = render_note(
        resolved, data, source=source, day=day, title=title
    )
    use_slug = _slugify(slug) if slug else auto_slug
    runs_dir = Path(vault_runs) if vault_runs else default_vault_runs_dir()
    runs_dir.mkdir(parents=True, exist_ok=True)
    out = runs_dir / f"{use_slug}.md"
    created = True
    if out.exists() and not force:
        # write sibling with timestamp
        use_slug = f"{use_slug}-{int(time.time()) % 100000}"
        out = runs_dir / f"{use_slug}.md"
    out.write_text(body, encoding="utf-8")
    if update_index:
        try:
            append_runs_index(
                runs_dir,
                day=day,
                slug=use_slug,
                title=title or use_slug,
                kind=rkind,
            )
        except Exception:
            pass
    return ExportResult(
        kind=rkind,
        path=out,
        title=title or use_slug,
        run_id=str(
            data.get("run_id")
            or data.get("mutation_id")
            or use_slug
        ),
        created=created,
    )
