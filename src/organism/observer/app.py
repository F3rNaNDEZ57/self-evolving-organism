"""
Phase 4 Streamlit observer — read-mostly dashboard.

Launch: seo ui   (or: streamlit run -m organism.observer.app)
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from organism.config import ROOT, experiment_config, resolve_path
from organism.observer.control import ControlState, load_control, save_control
from organism.observer.data import (
    active_genome_info,
    fmt_ts,
    genome_sources,
    get_mutation,
    lineage_edges,
    list_evaluations,
    list_events,
    list_genomes,
    list_mutations,
    load_json_artifact,
    open_store,
    pool_summary,
)


def _paths() -> tuple[Path, Path]:
    exp = experiment_config()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    return artifacts, db


def page_overview(artifacts: Path, db: Path) -> None:
    st.subheader("Overview")
    active = active_genome_info(artifacts)
    ctrl = load_control(artifacts)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Active genome", (active or {}).get("genome_id", "—"))
    with c2:
        fit = (active or {}).get("fitness")
        st.metric("Active fitness", f"{fit:.4f}" if isinstance(fit, (int, float)) else "—")
    with c3:
        st.metric("Mutations paused", "YES" if ctrl.mutations_paused else "no")
    with c4:
        st.metric("Frozen", "YES" if ctrl.frozen else "no")

    if active:
        st.json(active)

    ablate = load_json_artifact(artifacts, "last_ablation_report.json")
    if ablate:
        st.markdown("#### Last ablation")
        a1, a2, a3 = st.columns(3)
        with a1:
            st.metric("run_id", str(ablate.get("run_id", "—"))[:18])
        with a2:
            st.metric("δ (Bcw−B0)", f"{float(ablate.get('delta_holdout_bcw_minus_b0') or 0):.4f}")
        with a3:
            st.metric("success", str(bool(ablate.get("success"))))

    store = open_store(db)
    try:
        metrics = pool_summary(store)
        st.markdown("#### Pool metrics (SQLite)")
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("mutations", metrics.get("mutations_total", 0))
        with m2:
            st.metric("accept_rate", f"{float(metrics.get('accept_rate') or 0):.3f}")
        with m3:
            st.metric("critic_rejects", metrics.get("critic_rejects", 0))
        with m4:
            st.metric("tokens_total", metrics.get("tokens_total", 0))
    except Exception as e:
        st.warning(f"Metrics unavailable: {e}")
    finally:
        store.close()


def page_genomes(db: Path) -> None:
    st.subheader("Population / genomes")
    store = open_store(db)
    try:
        rows = list_genomes(store, limit=300)
        if not rows:
            st.info("No genomes in DB yet. Run `seo init` / mutate / ablate.")
            return
        # table
        display = [
            {
                "id": r.get("id"),
                "parent": r.get("parent_id") or "—",
                "status": r.get("status"),
                "ablation": r.get("ablation"),
                "last_fitness": r.get("last_fitness"),
                "created": fmt_ts(r.get("created_at")),
                "path": r.get("artifact_path"),
            }
            for r in rows
        ]
        st.dataframe(display, use_container_width=True, hide_index=True)
        gid = st.selectbox("Inspect genome sources", [r["id"] for r in rows])
        chosen = next(r for r in rows if r["id"] == gid)
        src = genome_sources(chosen.get("artifact_path"))
        if src:
            for name, text in src.items():
                with st.expander(name, expanded=(name == "policy.py")):
                    st.code(text, language="python")
        else:
            st.caption(f"No sources at {chosen.get('artifact_path')}")
    finally:
        store.close()


def page_lineage(db: Path) -> None:
    st.subheader("Lineage")
    store = open_store(db)
    try:
        edges = lineage_edges(store, limit=400)
        genomes = {r["id"]: r for r in list_genomes(store, limit=400)}
        if not edges and not genomes:
            st.info("No lineage data yet.")
            return
        # Simple text tree from roots
        children: dict[str, list[str]] = {}
        for p, c in edges:
            children.setdefault(p, []).append(c)
        all_ids = set(genomes) | {e[0] for e in edges} | {e[1] for e in edges}
        child_set = {c for _, c in edges}
        roots = sorted(all_ids - child_set) or sorted(all_ids)[:5]

        def _render(node: str, depth: int = 0, seen: set[str] | None = None) -> None:
            seen = seen or set()
            if node in seen or depth > 20:
                return
            seen.add(node)
            g = genomes.get(node, {})
            fit = g.get("last_fitness")
            fit_s = f"{fit:.3f}" if isinstance(fit, (int, float)) else "—"
            st.markdown(
                f"{'&nbsp;' * (depth * 4)}↳ `{node}` · "
                f"**{g.get('status', '?')}** · fit={fit_s} · {g.get('ablation') or '—'}",
                unsafe_allow_html=True,
            )
            for ch in children.get(node, []):
                _render(ch, depth + 1, seen)

        st.caption(f"{len(edges)} edges · {len(all_ids)} nodes")
        for r in roots[:30]:
            _render(r)
        st.markdown("#### Edges (parent → child)")
        st.dataframe(
            [{"parent": a, "child": b} for a, b in edges[:200]],
            use_container_width=True,
            hide_index=True,
        )
    finally:
        store.close()


def page_mutations(artifacts: Path, db: Path) -> None:
    st.subheader("Mutation inspector")
    store = open_store(db)
    try:
        muts = list_mutations(store, limit=150)
        if not muts:
            st.info("No mutations logged yet.")
            return
        labels = [
            f"{m['id']} · {m['decision']} · {fmt_ts(m.get('created_at'))}"
            for m in muts
        ]
        pick = st.selectbox("Mutation", range(len(labels)), format_func=lambda i: labels[i])
        mid = muts[pick]["id"]
        m = get_mutation(store, mid) or muts[pick]
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("decision", m.get("decision", "—"))
        with c2:
            st.metric("parent", str(m.get("parent_genome_id", "—"))[:16])
        with c3:
            st.metric("candidate", str(m.get("candidate_genome_id", "—"))[:16])
        st.write("**reason:**", m.get("reason") or "—")
        meta = m.get("meta") or {}
        st.markdown("#### Scores / critic / cost")
        st.json(
            {
                "parent_fitness": meta.get("parent_fitness"),
                "candidate_fitness": meta.get("candidate_fitness"),
                "epsilon": meta.get("epsilon"),
                "critic": meta.get("critic"),
                "llm_usage": m.get("llm") or meta.get("llm_usage"),
                "cost_per_accepted_gain_tokens": meta.get("cost_per_accepted_gain_tokens"),
                "files_changed": meta.get("files_changed"),
                "rationale": meta.get("rationale") or m.get("reason"),
            }
        )
        # sources
        cand = store.get_genome(str(m.get("candidate_genome_id") or ""))
        path = (cand or {}).get("artifact_path") if cand else None
        # rejected sources folder convention
        rej = artifacts / "mutations" / f"{mid}_rejected_sources"
        if rej.is_dir():
            path = str(rej)
        src = genome_sources(path)
        if src:
            st.markdown("#### Candidate sources")
            for name, text in src.items():
                with st.expander(name, expanded=False):
                    st.code(text, language="python")
        prop = artifacts / "mutations" / f"{mid}.json"
        if prop.exists():
            with st.expander("Raw mutation artifact JSON"):
                try:
                    st.json(json.loads(prop.read_text(encoding="utf-8")))
                except Exception:
                    st.text(prop.read_text(encoding="utf-8")[:8000])
    finally:
        store.close()


def page_timeline(db: Path) -> None:
    st.subheader("Event timeline")
    store = open_store(db)
    try:
        events = list_events(store, limit=200)
        if not events:
            st.info("No events yet.")
            return
        etype = st.multiselect(
            "Filter types",
            sorted({e.get("type") or "" for e in events}),
            default=[],
        )
        rows = []
        for e in events:
            if etype and e.get("type") not in etype:
                continue
            payload = e.get("payload") or {}
            rows.append(
                {
                    "time": fmt_ts(e.get("ts")),
                    "type": e.get("type"),
                    "summary": json.dumps(payload)[:160],
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)
        if rows:
            idx = int(
                st.number_input(
                    "Detail row index",
                    min_value=0,
                    max_value=max(0, len(rows) - 1),
                    value=0,
                )
            )
            sel = rows[idx]
            for e in events:
                if etype and e.get("type") not in etype:
                    continue
                if fmt_ts(e.get("ts")) == sel["time"] and e.get("type") == sel["type"]:
                    st.markdown("#### Payload")
                    st.json(e.get("payload"))
                    break
    finally:
        store.close()


def page_evaluations(db: Path) -> None:
    st.subheader("Evaluations")
    store = open_store(db)
    try:
        rows = list_evaluations(store, limit=150)
        st.dataframe(
            [
                {
                    "id": r.get("id"),
                    "genome": r.get("genome_id"),
                    "fitness": r.get("fitness"),
                    "mean": r.get("mean_score"),
                    "std": r.get("std_score"),
                    "created": fmt_ts(r.get("created_at")),
                }
                for r in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
    finally:
        store.close()


def page_control(artifacts: Path, db: Path) -> None:
    st.subheader("Kill switch / pause / freeze")
    st.caption("Read by `seo mutate` and `seo evolve` before genomic work. UI does not run the organism.")
    st_ctrl = load_control(artifacts)
    paused = st.checkbox("Pause mutations", value=st_ctrl.mutations_paused)
    frozen = st.checkbox("Freeze (hard stop)", value=st_ctrl.frozen)
    note = st.text_input("Operator note", value=st_ctrl.note)
    if st.button("Save control state", type="primary"):
        new = ControlState(
            mutations_paused=paused,
            frozen=frozen,
            note=note,
            updated_by="observer_ui",
        )
        path = save_control(artifacts, new)
        store = open_store(db)
        try:
            store.log_event(
                "operator_control",
                {"path": str(path), **new.to_dict()},
            )
        finally:
            store.close()
        st.success(f"Wrote {path}")
    st.json(load_control(artifacts).to_dict())
    st.markdown(f"`{artifacts / 'control.json'}`")


def main() -> None:
    st.set_page_config(
        page_title="SEO Observer",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("Self-Evolving Organism — Observer")
    st.caption("Phase 4 · read-mostly operator UI · not the organism brain")

    artifacts, db = _paths()
    st.sidebar.markdown("### Paths")
    st.sidebar.code(f"artifacts={artifacts}\ndb={db}\nroot={ROOT}", language="text")
    page = st.sidebar.radio(
        "Surface",
        [
            "Overview",
            "Genomes",
            "Lineage",
            "Mutations",
            "Timeline",
            "Evaluations",
            "Control",
        ],
    )
    if st.sidebar.button("Refresh"):
        st.rerun()

    if page == "Overview":
        page_overview(artifacts, db)
    elif page == "Genomes":
        page_genomes(db)
    elif page == "Lineage":
        page_lineage(db)
    elif page == "Mutations":
        page_mutations(artifacts, db)
    elif page == "Timeline":
        page_timeline(db)
    elif page == "Evaluations":
        page_evaluations(db)
    elif page == "Control":
        page_control(artifacts, db)


# streamlit runs this module
main()
