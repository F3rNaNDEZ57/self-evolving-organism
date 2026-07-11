"""
Phase 4 Streamlit observer — read-mostly dashboard.

Launch: seo ui   (or: streamlit run -m organism.observer.app)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
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


def page_run(artifacts: Path, db: Path) -> None:
    """Operator console: launch seo CLI jobs (not the organism brain)."""
    from organism.observer import jobs as jobmod

    st.subheader("Run experiment")
    st.caption(
        "Launches the same `seo` CLI in the background. Dry-run is default. "
        "Live free-NIM / long ablations need confirmation. Single job at a time."
    )

    busy, busy_id = jobmod.is_busy(artifacts)
    if busy:
        st.warning(f"Job running: `{busy_id}` — wait or kill below.")

    tab_mut, tab_evo, tab_ab, tab_w, tab_d = st.tabs(
        ["Mutate", "Evolve", "Ablate", "Weights", "Docker"]
    )

    with tab_mut:
        dry = st.checkbox("Dry-run (no NIM)", value=True, key="mut_dry")
        abl = st.selectbox("Ablation", ["Bc", "Bcw"], key="mut_abl")
        crit = st.checkbox("Critic", value=True, key="mut_crit")
        if st.button("Start mutate", type="primary", disabled=busy, key="mut_go"):
            if not dry and not st.session_state.get("mut_live_ok"):
                st.session_state["mut_live_ok"] = False
            try:
                if not dry:
                    st.session_state["pending_live_mutate"] = {
                        "ablation": abl,
                        "critic": crit,
                    }
                else:
                    rec = jobmod.start_job(
                        artifacts,
                        kind="mutate",
                        argv=jobmod.build_mutate_argv(
                            dry_run=True, ablation=abl, critic=crit
                        ),
                        note="ui mutate dry-run",
                    )
                    store = open_store(db)
                    try:
                        store.log_event(
                            "operator_job_start",
                            {"job_id": rec.job_id, "kind": rec.kind, "argv": rec.argv},
                        )
                    finally:
                        store.close()
                    st.success(f"Started {rec.job_id}")
                    st.rerun()
            except Exception as e:
                st.error(str(e))
        if st.session_state.get("pending_live_mutate"):
            st.error("Live mutate uses free NIM + Docker. Confirm to proceed.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Confirm LIVE mutate", type="primary", key="mut_live_yes"):
                    p = st.session_state.pop("pending_live_mutate")
                    try:
                        rec = jobmod.start_job(
                            artifacts,
                            kind="mutate",
                            argv=jobmod.build_mutate_argv(
                                dry_run=False,
                                ablation=p["ablation"],
                                critic=p["critic"],
                            ),
                            note="ui mutate LIVE",
                        )
                        store = open_store(db)
                        try:
                            store.log_event(
                                "operator_job_start",
                                {"job_id": rec.job_id, "kind": "mutate", "live": True},
                            )
                        finally:
                            store.close()
                        st.success(f"Started LIVE {rec.job_id}")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with c2:
                if st.button("Cancel", key="mut_live_no"):
                    st.session_state.pop("pending_live_mutate", None)
                    st.rerun()

    with tab_evo:
        dry_e = st.checkbox("Dry-run (no NIM)", value=True, key="evo_dry")
        cycles = st.number_input("Cycles", min_value=1, max_value=50, value=5, key="evo_c")
        max_m = st.number_input("Max mutations", min_value=0, max_value=30, value=5, key="evo_m")
        if st.button("Start evolve", type="primary", disabled=busy, key="evo_go"):
            if not dry_e:
                st.session_state["pending_live_evolve"] = {
                    "cycles": int(cycles),
                    "max_mutations": int(max_m),
                }
            else:
                try:
                    rec = jobmod.start_job(
                        artifacts,
                        kind="evolve",
                        argv=jobmod.build_evolve_argv(
                            dry_run=True,
                            cycles=int(cycles),
                            max_mutations=int(max_m),
                        ),
                        note="ui evolve dry-run",
                    )
                    st.success(f"Started {rec.job_id}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        if st.session_state.get("pending_live_evolve"):
            st.error("Live evolve uses free NIM. Confirm to proceed.")
            if st.button("Confirm LIVE evolve", type="primary", key="evo_yes"):
                p = st.session_state.pop("pending_live_evolve")
                try:
                    rec = jobmod.start_job(
                        artifacts,
                        kind="evolve",
                        argv=jobmod.build_evolve_argv(
                            dry_run=False,
                            cycles=p["cycles"],
                            max_mutations=p["max_mutations"],
                        ),
                        note="ui evolve LIVE",
                    )
                    st.success(f"Started LIVE {rec.job_id}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            if st.button("Cancel evolve", key="evo_no"):
                st.session_state.pop("pending_live_evolve", None)
                st.rerun()

    with tab_ab:
        quick = st.checkbox("Quick suite", value=True, key="ab_q")
        dry_a = st.checkbox("Dry-run mutations", value=True, key="ab_dry")
        max_a = st.number_input("Max mutations / code arm", min_value=0, max_value=30, value=3, key="ab_m")
        if st.button("Start ablate", type="primary", disabled=busy, key="ab_go"):
            if not dry_a and not quick:
                st.session_state["pending_live_ablate"] = {
                    "max_mutations": int(max_a),
                    "quick": False,
                }
            else:
                try:
                    rec = jobmod.start_job(
                        artifacts,
                        kind="ablate",
                        argv=jobmod.build_ablate_argv(
                            dry_run=dry_a or quick,
                            max_mutations=int(max_a),
                            quick=quick,
                        ),
                        note="ui ablate",
                    )
                    st.success(f"Started {rec.job_id}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        if st.session_state.get("pending_live_ablate"):
            st.error("Full live ablate can take hours and uses free NIM. Confirm.")
            if st.button("Confirm LIVE ablate", type="primary", key="ab_yes"):
                p = st.session_state.pop("pending_live_ablate")
                try:
                    rec = jobmod.start_job(
                        artifacts,
                        kind="ablate",
                        argv=jobmod.build_ablate_argv(
                            dry_run=False,
                            max_mutations=p["max_mutations"],
                            quick=False,
                        ),
                        note="ui ablate LIVE",
                    )
                    st.success(f"Started LIVE {rec.job_id}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
            if st.button("Cancel ablate", key="ab_no"):
                st.session_state.pop("pending_live_ablate", None)
                st.rerun()

    with tab_w:
        passes = st.number_input("Train passes", min_value=1, max_value=20, value=2, key="w_p")
        if st.button("Start weights train", type="primary", disabled=busy, key="w_go"):
            try:
                rec = jobmod.start_job(
                    artifacts,
                    kind="weights_train",
                    argv=jobmod.build_weights_train_argv(passes=int(passes)),
                    note="ui weights train",
                )
                st.success(f"Started {rec.job_id}")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    with tab_d:
        if st.button("Docker smoke", type="primary", disabled=busy, key="d_go"):
            try:
                rec = jobmod.start_job(
                    artifacts,
                    kind="docker_smoke",
                    argv=jobmod.build_docker_smoke_argv(),
                    note="ui docker-smoke",
                )
                st.success(f"Started {rec.job_id}")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("---")
    st.markdown("### Job status & log")
    jobs = jobmod.list_jobs(artifacts, limit=30)
    if not jobs:
        st.info("No jobs yet. Start one above.")
        return

    # Prefer the running job in the dropdown when one is active
    for j in jobs:
        if j.status in ("running", "queued"):
            jobmod.refresh_job(artifacts, j)
    jobs = jobmod.list_jobs(artifacts, limit=30)
    labels = [f"{j.job_id} · {j.kind} · {j.status}" for j in jobs]
    default_idx = 0
    for i, j in enumerate(jobs):
        if j.status in ("running", "queued"):
            default_idx = i
            break
    pick = st.selectbox(
        "Job",
        range(len(labels)),
        index=default_idx,
        format_func=lambda i: labels[i],
        key="job_pick",
    )
    rec0 = jobs[pick]

    live = st.toggle(
        "Live logs (auto-refresh while running)",
        value=True,
        key="job_live_logs",
        help="Polls the job log every 2s without a full page refresh.",
    )
    any_running = any(j.status in ("running", "queued") for j in jobs)
    # Fragment re-runs only when live mode is on and something is (or might be) running
    run_every = timedelta(seconds=2) if (live and any_running) else None

    @st.fragment(run_every=run_every)
    def _job_status_panel() -> None:
        rec = jobmod.load_job(artifacts, rec0.job_id) or rec0
        rec = jobmod.refresh_job(artifacts, rec)

        # When a job finishes, full-rerun once so we drop the 2s poll interval
        prev = st.session_state.get("_job_live_status")
        st.session_state["_job_live_status"] = rec.status
        if (
            live
            and prev in ("running", "queued")
            and rec.status not in ("running", "queued")
        ):
            st.rerun()

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("status", rec.status)
        with c2:
            st.metric("pid", rec.pid or "—")
        with c3:
            st.metric(
                "returncode",
                rec.returncode if rec.returncode is not None else "—",
            )
        with c4:
            st.metric("kind", rec.kind)

        st.code(" ".join(rec.argv), language="text")
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("Refresh log now", key="job_ref"):
                st.rerun(scope="fragment")
        with b2:
            if rec.status == "running" and st.button(
                "Kill job", type="primary", key="job_kill"
            ):
                jobmod.kill_job(artifacts, rec.job_id)
                st.warning("Kill signal sent")
                st.rerun(scope="fragment")
        with b3:
            if rec.status == "running" and st.button(
                "Soft pause (control.json)", key="job_soft"
            ):
                save_control(
                    artifacts,
                    ControlState(
                        mutations_paused=True,
                        note=f"paused from UI during {rec.job_id}",
                    ),
                )
                st.info("Paused next mutations via control.json")

        log = jobmod.tail_log(artifacts, rec.job_id, max_bytes=48_000) or "(empty)"
        if rec.status in ("running", "queued") and live:
            st.caption(
                f"Live · last refresh {datetime.now().strftime('%H:%M:%S')} · every 2s"
            )
        elif rec.status in ("running", "queued"):
            st.caption("Live logs off — use Refresh log now, or enable the toggle above.")
        else:
            st.caption(f"Job {rec.status} · static log")

        st.markdown("#### Log tail")
        # code block keeps monospace + scroll; show newest end of long logs
        st.code(log, language="text")

    _job_status_panel()


def main() -> None:
    st.set_page_config(
        page_title="SEO Observer",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("Self-Evolving Organism — Observer")
    st.caption("Phase 4 · operator console · inspect + launch seo jobs · not the organism brain")

    artifacts, db = _paths()
    st.sidebar.markdown("### Paths")
    st.sidebar.code(f"artifacts={artifacts}\ndb={db}\nroot={ROOT}", language="text")
    page = st.sidebar.radio(
        "Surface",
        [
            "Overview",
            "Run",
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
    elif page == "Run":
        page_run(artifacts, db)
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
