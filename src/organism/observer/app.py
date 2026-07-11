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

    st.markdown("#### Export lab note")
    st.caption(
        "Write a markdown note under `self-evolving-organism-docs/Runs/` from the "
        "newest machine report (evolve / ablate / mutation)."
    )
    ek = st.selectbox(
        "Report kind",
        ["auto", "evolve", "ablate", "mutation", "weights_holdout"],
        key="export_kind",
    )
    if st.button("Export to Runs/", type="primary", key="export_run_btn"):
        try:
            from organism.runs_export import export_run_note

            res = export_run_note(artifacts, kind=ek, update_index=True)
            st.success(f"Wrote `{res.path.name}` ({res.kind}) · run_id={res.run_id}")
            st.code(str(res.path), language="text")
        except Exception as e:
            st.error(str(e))


def page_genomes(artifacts: Path, db: Path) -> None:
    st.subheader("Population / genomes")
    from organism.elites import demote_elite, is_elite, list_elites, promote_elite

    store = open_store(db)
    try:
        rows = list_genomes(store, limit=300)
        elite_ids = {str(e.get("genome_id")) for e in list_elites(artifacts)}
        if not rows:
            st.info("No genomes in DB yet. Run `seo init` / mutate / ablate.")
            return
        # table
        display = [
            {
                "id": r.get("id"),
                "parent": r.get("parent_id") or "—",
                "status": r.get("status"),
                "elite": "yes" if str(r.get("id")) in elite_ids else "",
                "ablation": r.get("ablation"),
                "last_fitness": r.get("last_fitness"),
                "created": fmt_ts(r.get("created_at")),
                "path": r.get("artifact_path"),
            }
            for r in rows
        ]
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown("#### Elite archive (Phase 5)")
        elites = list_elites(artifacts)
        if elites:
            st.dataframe(
                [
                    {
                        "genome_id": e.get("genome_id"),
                        "fitness": e.get("fitness"),
                        "path_ok": e.get("path_ok"),
                        "note": e.get("note"),
                        "path": e.get("path"),
                    }
                    for e in elites
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No elites yet — promote a genome below.")

        gid = st.selectbox("Inspect / promote genome", [r["id"] for r in rows], key="gen_pick")
        chosen = next(r for r in rows if r["id"] == gid)
        note = st.text_input("Elite note", value="", key="gen_elite_note")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Promote to elite", type="primary", key="gen_promote"):
                try:
                    fit = chosen.get("last_fitness")
                    entry = promote_elite(
                        artifacts,
                        store,
                        str(gid),
                        note=note,
                        fitness=float(fit) if isinstance(fit, (int, float)) else None,
                    )
                    st.success(f"Elite: {entry.get('genome_id')}")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        with c2:
            if is_elite(artifacts, str(gid)) and st.button("Demote elite", key="gen_demote"):
                demote_elite(artifacts, store, str(gid))
                st.warning(f"Demoted {gid}")
                st.rerun()

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
        from organism.elites import list_elites
        from organism.mutation import resolve_parent_genome

        dry = st.checkbox("Dry-run (no NIM)", value=True, key="mut_dry")
        abl = st.selectbox("Ablation", ["Bc", "Bcw"], key="mut_abl")
        crit = st.checkbox("Critic", value=True, key="mut_crit")
        mut_select = st.selectbox(
            "Auto-select policy",
            ["active", "fitness_rank", "tournament"],
            key="mut_select",
            help="Used when Parent is 'auto' — fitness_rank / tournament over elites+DB",
        )
        mut_k = st.number_input(
            "Tournament k", min_value=2, max_value=10, value=3, key="mut_k"
        )
        # Parent: auto (policy) · active · elite / recent genome
        try:
            exp = experiment_config()
            active_path, active_id = resolve_parent_genome(exp)
        except Exception:
            active_id, active_path = "active", Path(".")
        parent_choices: list[tuple[str, str]] = [
            (f"auto · policy={mut_select}", "__auto__"),
            (f"active · {active_id}", ""),  # empty parent_id → active pointer
        ]
        for e in list_elites(artifacts):
            gid = str(e.get("genome_id") or "")
            if not gid:
                continue
            fit = e.get("fitness")
            fit_s = f"{float(fit):.3f}" if isinstance(fit, (int, float)) else "?"
            label = f"elite · {gid} · fit={fit_s}"
            parent_choices.append((label, gid))
        store_g = open_store(db)
        try:
            for r in list_genomes(store_g, limit=40):
                gid = str(r.get("id") or "")
                if not gid or any(gid == p[1] for p in parent_choices):
                    continue
                if gid == active_id:
                    continue
                parent_choices.append(
                    (f"genome · {gid} · {r.get('status') or '?'}", gid)
                )
        finally:
            store_g.close()
        parent_i = st.selectbox(
            "Parent genome",
            range(len(parent_choices)),
            format_func=lambda i: parent_choices[i][0],
            key="mut_parent",
            help="Phase 5: auto policy, active, elite, or any known genome",
        )
        parent_raw = parent_choices[parent_i][1]
        if parent_raw == "__auto__":
            parent_id = ""
            select_policy = mut_select
            st.caption(f"Auto-select `{mut_select}` (tournament k={int(mut_k)})")
        else:
            parent_id = parent_raw
            select_policy = "active"
            if parent_id:
                st.caption(f"Will pass `--parent-id {parent_id}`")
            else:
                st.caption(f"Uses active parent `{active_id}`")

        if st.button("Start mutate", type="primary", disabled=busy, key="mut_go"):
            if not dry and not st.session_state.get("mut_live_ok"):
                st.session_state["mut_live_ok"] = False
            try:
                if not dry:
                    st.session_state["pending_live_mutate"] = {
                        "ablation": abl,
                        "critic": crit,
                        "parent_id": parent_id,
                        "select": select_policy,
                        "tournament_k": int(mut_k),
                    }
                else:
                    rec = jobmod.start_job(
                        artifacts,
                        kind="mutate",
                        argv=jobmod.build_mutate_argv(
                            dry_run=True,
                            ablation=abl,
                            critic=crit,
                            parent_id=parent_id,
                            select=select_policy,
                            tournament_k=int(mut_k),
                        ),
                        note=(
                            f"ui mutate dry-run "
                            f"parent={parent_id or select_policy}"
                        ),
                    )
                    store = open_store(db)
                    try:
                        store.log_event(
                            "operator_job_start",
                            {
                                "job_id": rec.job_id,
                                "kind": rec.kind,
                                "argv": rec.argv,
                                "parent_id": parent_id or active_id,
                            },
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
                                parent_id=p.get("parent_id") or "",
                                select=p.get("select") or "active",
                                tournament_k=int(p.get("tournament_k") or 3),
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
        evo_select = st.selectbox(
            "Parent selection",
            ["active", "fitness_rank", "tournament"],
            key="evo_select",
            help="fitness_rank / tournament re-pick parent from elites before each mutation",
        )
        evo_k = st.number_input(
            "Tournament k", min_value=2, max_value=10, value=3, key="evo_k"
        )
        evo_lineages = st.number_input(
            "Lineages (concurrent slots)",
            min_value=1,
            max_value=8,
            value=1,
            key="evo_lineages",
            help=">1 enables multi-lineage evolve with budgets",
        )
        evo_mut_pl = st.number_input(
            "Max mut / lineage (0=off)",
            min_value=0,
            max_value=30,
            value=0,
            key="evo_mut_pl",
        )
        evo_cyc_pl = st.number_input(
            "Max cycles / lineage (0=off)",
            min_value=0,
            max_value=50,
            value=0,
            key="evo_cyc_pl",
        )
        evo_sched = st.selectbox(
            "Lineage schedule",
            ["round_robin", "fitness_rank"],
            key="evo_sched",
        )
        if st.button("Start evolve", type="primary", disabled=busy, key="evo_go"):
            if not dry_e:
                st.session_state["pending_live_evolve"] = {
                    "cycles": int(cycles),
                    "max_mutations": int(max_m),
                    "select": evo_select,
                    "tournament_k": int(evo_k),
                    "lineages": int(evo_lineages),
                    "mut_per_lineage": int(evo_mut_pl),
                    "cycles_per_lineage": int(evo_cyc_pl),
                    "lineage_schedule": evo_sched,
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
                            select=evo_select,
                            tournament_k=int(evo_k),
                            lineages=int(evo_lineages),
                            mut_per_lineage=int(evo_mut_pl),
                            cycles_per_lineage=int(evo_cyc_pl),
                            lineage_schedule=evo_sched,
                        ),
                        note=f"ui evolve dry-run select={evo_select} L={int(evo_lineages)}",
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
                            select=p.get("select") or "active",
                            tournament_k=int(p.get("tournament_k") or 3),
                            lineages=int(p.get("lineages") or 1),
                            mut_per_lineage=int(p.get("mut_per_lineage") or 0),
                            cycles_per_lineage=int(p.get("cycles_per_lineage") or 0),
                            lineage_schedule=str(
                                p.get("lineage_schedule") or "round_robin"
                            ),
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
        st.markdown("##### Holdout: B0 vs Bw")
        st.caption(
            "Compare holdout fitness with a frozen checkpoint (real Bw measurement)."
        )
        wh_ref = st.selectbox(
            "Checkpoint",
            ["latest", "best"],
            key="w_holdout_ref",
        )
        wh_passes = st.number_input(
            "Train first (0 = use existing checkpoint)",
            min_value=0,
            max_value=20,
            value=0,
            key="w_holdout_p",
        )
        if st.button("Start B0 vs Bw holdout", disabled=busy, key="w_holdout_go"):
            try:
                rec = jobmod.start_job(
                    artifacts,
                    kind="weights_holdout",
                    argv=jobmod.build_weights_holdout_argv(
                        weights=str(wh_ref),
                        passes=int(wh_passes),
                        host=True,
                    ),
                    note=f"ui weights holdout {wh_ref} p={int(wh_passes)}",
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

    # --- Launch plan: live form values (not the selected past job) ---
    st.markdown("---")
    st.markdown("### Launch plan (current form)")
    st.caption(
        "These are the controls you set in the tabs above — what the next Start would run. "
        "They are **not** the same as Job parameters below (that is history of a job that already ran)."
    )

    ss = st.session_state
    mut_dry = bool(ss.get("mut_dry", True))
    mut_abl = str(ss.get("mut_abl", "Bc"))
    mut_crit = bool(ss.get("mut_crit", True))
    mut_select = str(ss.get("mut_select", "active"))
    mut_k = int(ss.get("mut_k", 3))
    # Rebuild parent list: auto, active, elites, genomes
    mut_parent_id = ""
    mut_sel_eff = mut_select
    try:
        from organism.elites import list_elites
        from organism.mutation import resolve_parent_genome as rpg2

        _, aid2 = rpg2(experiment_config())
        pcs: list[str] = ["__auto__", ""]
        for e in list_elites(artifacts):
            gid = str(e.get("genome_id") or "")
            if gid:
                pcs.append(gid)
        store_lp = open_store(db)
        try:
            for r in list_genomes(store_lp, limit=40):
                gid = str(r.get("id") or "")
                if gid and gid not in pcs and gid != aid2:
                    pcs.append(gid)
        finally:
            store_lp.close()
        idx = int(ss.get("mut_parent", 0) or 0)
        if 0 <= idx < len(pcs):
            raw = pcs[idx]
            if raw == "__auto__":
                mut_parent_id = ""
                mut_sel_eff = mut_select
            else:
                mut_parent_id = raw
                mut_sel_eff = "active"
    except Exception:
        mut_parent_id = ""
        mut_sel_eff = mut_select
    evo_dry = bool(ss.get("evo_dry", True))
    evo_c = int(ss.get("evo_c", 5))
    evo_m = int(ss.get("evo_m", 5))
    evo_select = str(ss.get("evo_select", "active"))
    evo_k = int(ss.get("evo_k", 3))
    evo_lineages = int(ss.get("evo_lineages", 1))
    evo_mut_pl = int(ss.get("evo_mut_pl", 0))
    evo_cyc_pl = int(ss.get("evo_cyc_pl", 0))
    evo_sched = str(ss.get("evo_sched", "round_robin"))
    ab_q = bool(ss.get("ab_q", True))
    ab_dry = bool(ss.get("ab_dry", True))
    ab_m = int(ss.get("ab_m", 3))
    w_p = int(ss.get("w_p", 2))

    launch_rows = [
        {
            "tab": "Mutate",
            "mode": "dry-run" if mut_dry else "LIVE",
            "parameters": (
                f"ablation={mut_abl}, critic={mut_crit}, "
                f"parent={mut_parent_id or mut_sel_eff}, select={mut_sel_eff}"
            ),
            "argv_preview": " ".join(
                jobmod.build_mutate_argv(
                    dry_run=mut_dry,
                    ablation=mut_abl,
                    critic=mut_crit,
                    parent_id=mut_parent_id,
                    select=mut_sel_eff,
                    tournament_k=mut_k,
                )[3:]  # drop python -m organism.cli
            ),
        },
        {
            "tab": "Evolve",
            "mode": "dry-run" if evo_dry else "LIVE",
            "parameters": (
                f"cycles={evo_c}, max_mutations={evo_m}, "
                f"select={evo_select}, k={evo_k}, "
                f"lineages={evo_lineages}, sched={evo_sched}"
            ),
            "argv_preview": " ".join(
                jobmod.build_evolve_argv(
                    dry_run=evo_dry,
                    cycles=evo_c,
                    max_mutations=evo_m,
                    select=evo_select,
                    tournament_k=evo_k,
                    lineages=evo_lineages,
                    mut_per_lineage=evo_mut_pl,
                    cycles_per_lineage=evo_cyc_pl,
                    lineage_schedule=evo_sched,
                )[3:]
            ),
        },
        {
            "tab": "Ablate",
            "mode": (
                "quick/dry"
                if ab_q
                else ("dry-run" if ab_dry else "LIVE")
            ),
            "parameters": f"quick={ab_q}, dry_run={ab_dry or ab_q}, max_mutations={ab_m}",
            "argv_preview": " ".join(
                jobmod.build_ablate_argv(
                    dry_run=ab_dry or ab_q, max_mutations=ab_m, quick=ab_q
                )[3:]
            ),
        },
        {
            "tab": "Weights",
            "mode": "train / holdout",
            "parameters": (
                f"train_passes={w_p}; holdout={ss.get('w_holdout_ref', 'latest')} "
                f"p={ss.get('w_holdout_p', 0)}"
            ),
            "argv_preview": " ".join(
                jobmod.build_weights_train_argv(passes=w_p)[3:]
            )
            + " | "
            + " ".join(
                jobmod.build_weights_holdout_argv(
                    weights=str(ss.get("w_holdout_ref", "latest")),
                    passes=int(ss.get("w_holdout_p", 0) or 0),
                )[3:]
            ),
        },
        {
            "tab": "Docker",
            "mode": "smoke",
            "parameters": "(no options)",
            "argv_preview": " ".join(jobmod.build_docker_smoke_argv()[3:]),
        },
    ]
    st.dataframe(launch_rows, use_container_width=True, hide_index=True)

    with st.expander("Full command lines that Start would launch", expanded=False):
        for row in launch_rows:
            st.markdown(f"**{row['tab']}** ({row['mode']})")
            full = " ".join(
                {
                    "Mutate": jobmod.build_mutate_argv(
                        dry_run=mut_dry,
                        ablation=mut_abl,
                        critic=mut_crit,
                        parent_id=mut_parent_id,
                        select=mut_sel_eff,
                        tournament_k=mut_k,
                    ),
                    "Evolve": jobmod.build_evolve_argv(
                        dry_run=evo_dry,
                        cycles=evo_c,
                        max_mutations=evo_m,
                        select=evo_select,
                        tournament_k=evo_k,
                        lineages=evo_lineages,
                        mut_per_lineage=evo_mut_pl,
                        cycles_per_lineage=evo_cyc_pl,
                        lineage_schedule=evo_sched,
                    ),
                    "Ablate": jobmod.build_ablate_argv(
                        dry_run=ab_dry or ab_q, max_mutations=ab_m, quick=ab_q
                    ),
                    "Weights": jobmod.build_weights_train_argv(passes=w_p),
                    "Docker": jobmod.build_docker_smoke_argv(),
                }[row["tab"]]
            )
            st.code(full, language="text")

    st.markdown("---")
    st.markdown("### Job status & log")
    st.caption(
        "History of jobs that were actually started. Pick one to inspect its "
        "parameters, final result, and log — independent of the form above."
    )
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
    # Keep selection stable via job_id (not list index, which shifts as jobs are added)
    id_to_idx = {j.job_id: i for i, j in enumerate(jobs)}
    running_id = next(
        (j.job_id for j in jobs if j.status in ("running", "queued")), None
    )
    if "job_pick_id" not in ss or ss["job_pick_id"] not in id_to_idx:
        ss["job_pick_id"] = running_id or jobs[0].job_id
    # When a new job starts (busy), auto-focus it once
    if running_id and ss.get("_job_autofocus") != running_id:
        ss["job_pick_id"] = running_id
        ss["_job_autofocus"] = running_id
    pick_ids = [j.job_id for j in jobs]
    pick_id = st.selectbox(
        "Job",
        pick_ids,
        format_func=lambda jid: labels[id_to_idx[jid]],
        key="job_pick_id",
    )
    rec0 = jobs[id_to_idx[pick_id]]

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

        detail = jobmod.job_parameters(rec)
        cli = detail.get("cli") or {}
        finished = rec.status not in ("running", "queued")
        result = jobmod.load_job_result(artifacts, rec.job_id) if finished else None
        # Backfill snapshot for older jobs / race after exit
        if finished and result is None:
            try:
                dest = jobmod.snapshot_job_result(artifacts, rec)
                rec.result_path = str(dest)
                jobmod.save_job(artifacts, rec)
                result = jobmod.load_job_result(artifacts, rec.job_id)
            except Exception:
                result = None

        # Parameters stay open for the selected job (running and finished)
        with st.expander("Job parameters", expanded=True):
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                st.metric("command", str(cli.get("command") or rec.kind))
            with p2:
                dry = cli.get("dry_run")
                if dry is True:
                    mode_s = "dry-run"
                elif dry is False:
                    mode_s = "live"
                elif rec.kind == "weights_train":
                    mode_s = "train"
                elif rec.kind == "docker_smoke":
                    mode_s = "smoke"
                else:
                    mode_s = "n/a"
                st.metric("mode", mode_s)
            with p3:
                dur = detail.get("duration_s")
                st.metric(
                    "duration",
                    f"{dur:.1f}s" if isinstance(dur, (int, float)) else "—",
                )
            with p4:
                st.metric("note", (rec.note or "—")[:28])

            flag_rows = {k: v for k, v in cli.items() if k not in ("command",)}
            if flag_rows:
                st.markdown("**CLI flags**")
                st.table(
                    [
                        {"parameter": k, "value": str(v)}
                        for k, v in sorted(flag_rows.items())
                    ]
                )

            st.markdown("**Timing**")
            st.table(
                [
                    {"field": "created_at", "value": fmt_ts(detail.get("created_at"))},
                    {"field": "started_at", "value": fmt_ts(detail.get("started_at"))},
                    {"field": "ended_at", "value": fmt_ts(detail.get("ended_at"))},
                    {
                        "field": "duration_s",
                        "value": (
                            f"{detail['duration_s']:.2f}"
                            if detail.get("duration_s") is not None
                            else "—"
                        ),
                    },
                ]
            )

            st.markdown("**Paths**")
            st.code(
                "\n".join(
                    [
                        f"log:    {rec.log_path or '—'}",
                        f"meta:   {rec.meta_path or '—'}",
                        f"result: {rec.result_path or '—'}",
                    ]
                ),
                language="text",
            )
            if rec.error:
                st.error(rec.error)

            st.markdown("**Full argv**")
            st.code(" ".join(rec.argv), language="text")

            with st.expander("Raw job record JSON", expanded=False):
                st.json(detail)

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

        # Final result stays visible after the job ends
        if finished:
            st.markdown("#### Final result")
            if rec.status == "succeeded":
                st.success(
                    f"**{rec.job_id}** succeeded"
                    + (
                        f" · exit {rec.returncode}"
                        if rec.returncode is not None
                        else ""
                    )
                )
            elif rec.status == "failed":
                st.error(
                    f"**{rec.job_id}** failed"
                    + (
                        f" · exit {rec.returncode}"
                        if rec.returncode is not None
                        else ""
                    )
                )
            else:
                st.warning(f"**{rec.job_id}** · {rec.status}")

            headline = None
            if result and isinstance(result.get("summary"), dict):
                headline = result["summary"].get("headline") or result["summary"].get(
                    "decision"
                )
            if headline:
                st.info(str(headline))

            if result and result.get("artifact") is not None:
                with st.expander("Structured result (CLI artifact)", expanded=True):
                    st.json(result["artifact"])

            log_full = ""
            if result and result.get("log"):
                log_full = str(result["log"])
            else:
                log_full = jobmod.read_log(artifacts, rec.job_id) or "(empty)"
            st.markdown("#### Final log")
            st.caption("Full job log (persisted with the job — still available after exit)")
            st.code(log_full or "(empty)", language="text")
        else:
            log = jobmod.tail_log(artifacts, rec.job_id, max_bytes=48_000) or "(empty)"
            if live:
                st.caption(
                    f"Live · last refresh {datetime.now().strftime('%H:%M:%S')} · every 2s"
                )
            else:
                st.caption(
                    "Live logs off — use Refresh log now, or enable the toggle above."
                )
            st.markdown("#### Log tail")
            st.code(log, language="text")

    _job_status_panel()


def page_watch(artifacts: Path, db: Path) -> None:
    """See the organism on the grid — host episode live stream / video (not the brain)."""
    import time as time_mod

    from organism.checkpoints import list_checkpoints, resolve_checkpoint_path
    from organism.evaluator import FitnessConfig, episode_score
    from organism.genome_loader import make_policy_factory
    from organism.replay import (
        EpisodeReplay,
        frame_to_rgb,
        iter_episode,
        record_episode,
        replay_to_gif,
        trail_up_to,
    )
    from organism.schemas import EpisodeSummary
    from organism.world import WorldConfig
    from organism.weights import WeightConfig

    st.subheader("Watch")
    st.caption(
        "Live video-style stream on the food grid. "
        "Single agent = science policy path. Multi-agent = viz-only same-map arena "
        "(not used for fitness claims)."
    )

    exp = experiment_config()
    world = WorldConfig.from_dict(exp.get("world", {}))
    fit = FitnessConfig.from_dict(exp.get("fitness", {}), exp.get("world", {}))
    wcfg_d = exp.get("weights", {}) or {}
    wcfg = WeightConfig(
        alpha=float(wcfg_d.get("alpha", 0.02)),
        init_std=float(wcfg_d.get("init_std", 0.01)),
        clip_abs=float(wcfg_d.get("clip_abs", 5.0)),
        explore_train=float(wcfg_d.get("explore_train", 0.10)),
        explore_eval=float(wcfg_d.get("explore_eval", 0.0)),
    )

    active = active_genome_info(artifacts) or {}
    store = open_store(db)
    try:
        genomes = list_genomes(store, limit=80)
    finally:
        store.close()

    seed_dir = ROOT / "genomes" / "seed"
    options: list[tuple[str, str]] = []
    if active.get("genome_id") and active.get("path"):
        options.append((f"active · {active['genome_id']}", str(active["path"])))
    options.append(("seed genome", str(seed_dir)))
    for g in genomes:
        gid = str(g.get("id") or "")
        ap = str(g.get("artifact_path") or "")
        if gid and ap and Path(ap).exists():
            label = f"{gid} · {g.get('status') or '?'}"
            if not any(o[1] == ap for o in options):
                options.append((label, ap))

    if not options:
        st.warning("No genomes found.")
        return

    watch_mode = st.radio(
        "Mode",
        ["single", "multi"],
        horizontal=True,
        key="watch_mode",
        help="multi = several genomes compete on one shared food map (viz only)",
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        if watch_mode == "single":
            pick = st.selectbox(
                "Genome",
                range(len(options)),
                format_func=lambda i: options[i][0],
                key="watch_genome",
            )
            genome_path = Path(options[pick][1])
            genome_id = (
                options[pick][0].split("·")[0].strip().replace("active ", "").strip()
            )
            if genome_id == "seed genome":
                genome_id = "g_seed"
            multi_picks: list[int] = [pick]
        else:
            multi_picks = st.multiselect(
                "Agents (2–6 genomes)",
                options=list(range(len(options))),
                default=list(range(min(2, len(options)))),
                format_func=lambda i: options[i][0],
                key="watch_multi_genomes",
            )
            genome_path = Path(options[0][1])
            genome_id = "multi"
    with c2:
        ablation = st.selectbox(
            "Ablation (policy mode)",
            ["Bc", "B0", "Bw", "Bcw"],
            key="watch_abl",
        )
        seed = st.number_input(
            "Episode seed", min_value=0, max_value=10_000, value=0, key="watch_seed"
        )
    with c3:
        show_trail = st.checkbox("Show path trail", value=True, key="watch_trail")
        cell = st.slider("Cell size (px)", 8, 32, 18, key="watch_cell")
        speed = st.select_slider(
            "Video speed (ms / frame)",
            options=[30, 50, 80, 120, 200, 350, 500],
            value=80,
            key="watch_speed",
        )
        weight_ref = ""
        if ablation in ("Bw", "Bcw"):
            cps = list_checkpoints(artifacts)[:20]
            weight_ref = st.selectbox(
                "Weights",
                ["(none)", "latest", "best"] + [c.checkpoint_id for c in cps],
                key="watch_w",
            )

    if watch_mode == "multi":
        st.markdown(
            "**Legend (multi):** dark=empty · green=food · "
            "yellow/cyan/pink/orange/… = agents · dark red=dead · blue-gray=trail"
        )
    else:
        st.markdown(
            "**Legend:** dark=empty · green=food · yellow=agent · red=dead · blue-gray=trail"
        )

    def _resolve_weights():
        if ablation not in ("Bw", "Bcw") or not weight_ref or weight_ref == "(none)":
            return None
        try:
            return resolve_checkpoint_path(artifacts, weight_ref)
        except Exception as e:
            st.error(f"weights: {e}")
            return None

    def _make_policy(gpath: Path | None = None):
        return make_policy_factory(
            gpath or genome_path,
            ablation=ablation,
            weight_cfg=wcfg,
            weight_path=_resolve_weights(),
            force_train=False,
        )()

    def _make_multi_policies():
        picks = multi_picks or []
        if len(picks) < 2:
            # auto-fill from available options
            picks = list(range(min(3, len(options))))
        picks = picks[:6]
        out = []
        for i in picks:
            label, pth = options[int(i)]
            gid = label.split("·")[0].strip().replace("active ", "").strip()
            if gid == "seed genome":
                gid = "g_seed"
            out.append((gid, _make_policy(Path(pth))))
        return out

    b_live, b_rec = st.columns(2)
    live_clicked = b_live.button(
        "Live stream (video)",
        type="primary",
        key="watch_live",
        help="Run the episode now and paint each step like a video",
        disabled=(watch_mode == "multi" and len(multi_picks or []) < 2 and len(options) < 2),
    )
    rec_clicked = b_rec.button(
        "Record only (then scrub)",
        key="watch_go",
        help="Run fully first, then scrub frames / autoplay / GIF",
    )

    # --- Multi-agent same-map (viz only) ---
    if watch_mode == "multi" and (live_clicked or rec_clicked):
        from organism.multiagent import (
            iter_multi_episode,
            multi_frame_to_rgb,
            multi_replay_to_gif,
            record_multi_episode,
            trails_up_to,
        )

        try:
            policies = _make_multi_policies()
            if len(policies) < 2:
                st.error("Pick at least 2 agents for multi mode.")
            elif live_clicked:
                st.session_state["watch_playing"] = False
                stage = st.empty()
                status = st.empty()
                frames_m = []
                status.info(f"Live multi-agent stream · {len(policies)} agents…")
                delay = max(0.0, float(speed) / 1000.0)
                for fr, done, err_s in iter_multi_episode(
                    policies,
                    world,
                    seed=int(seed),
                    episode_timeout_s=float(fit.episode_timeout_s or 30),
                ):
                    frames_m.append(fr)
                    trails = trails_up_to(frames_m, len(frames_m) - 1) if show_trail else None
                    rgb = multi_frame_to_rgb(fr, cell=int(cell), trails=trails)
                    with stage.container():
                        left, right = st.columns([1.4, 1])
                        with left:
                            st.image(
                                rgb,
                                caption=f"MULTI tick={fr.tick} agents={len(fr.agents)}",
                                use_container_width=False,
                            )
                        with right:
                            for i, a in enumerate(fr.agents):
                                st.metric(
                                    f"[{i}] {a.genome_id[:14]}",
                                    f"food={a.food_collected} E={a.energy:.0f}",
                                )
                                st.caption(
                                    f"({a.x},{a.y}) {a.action_name()} "
                                    f"{'alive' if a.alive else 'dead'}"
                                )
                    if done:
                        if err_s:
                            status.error(err_s)
                        break
                    time_mod.sleep(delay)
                from organism.multiagent import MultiReplay

                mrep = MultiReplay(
                    frames=frames_m,
                    seed=int(seed),
                    genome_ids=[g for g, _ in policies],
                    ablation=ablation,
                    final=[
                        {
                            "genome_id": a.genome_id,
                            "food_collected": a.food_collected,
                            "energy": a.energy,
                            "alive": a.alive,
                        }
                        for a in (frames_m[-1].agents if frames_m else [])
                    ],
                )
                st.session_state["watch_multi_replay"] = mrep
                st.session_state.pop("watch_replay", None)
                try:
                    gif_path = artifacts / "replays" / "_last_watch_multi.gif"
                    multi_replay_to_gif(
                        mrep,
                        gif_path,
                        cell=max(8, int(cell) - 4),
                        duration_ms=int(speed),
                        show_trail=show_trail,
                    )
                    st.session_state["watch_gif_path"] = str(gif_path)
                except Exception:
                    pass
                status.success(
                    f"Multi stream done · {len(frames_m)} frames · "
                    f"agents={len(policies)}"
                )
            else:
                with st.spinner("Recording multi-agent episode…"):
                    mrep = record_multi_episode(
                        policies,
                        world,
                        seed=int(seed),
                        ablation=ablation,
                        episode_timeout_s=float(fit.episode_timeout_s or 30),
                    )
                st.session_state["watch_multi_replay"] = mrep
                st.session_state.pop("watch_replay", None)
                st.session_state["watch_frame_idx"] = 0
                if mrep.error:
                    st.error(mrep.error)
                else:
                    st.success(
                        f"Multi recorded {len(mrep.frames)} frames · "
                        f"agents={len(mrep.genome_ids)}"
                    )
                    try:
                        gif_path = artifacts / "replays" / "_last_watch_multi.gif"
                        multi_replay_to_gif(
                            mrep,
                            gif_path,
                            cell=max(8, int(cell) - 4),
                            duration_ms=int(speed),
                            show_trail=show_trail,
                        )
                        st.session_state["watch_gif_path"] = str(gif_path)
                    except Exception:
                        pass
        except Exception as e:
            st.exception(e)
        # stay on multi UI after run/error
        if watch_mode == "multi" and not st.session_state.get("watch_multi_replay"):
            st.info("Pick ≥2 genomes, then Live stream or Record.")
            return

    # Multi replay viewer
    mrep = st.session_state.get("watch_multi_replay")
    if watch_mode == "multi" and mrep and getattr(mrep, "frames", None):
        from organism.multiagent import multi_frame_to_rgb, multi_replay_to_gif, trails_up_to

        gif_p = st.session_state.get("watch_gif_path")
        if gif_p and Path(gif_p).exists():
            st.markdown("#### Multi video loop (GIF)")
            st.image(str(gif_p), caption="Multi-agent GIF")
        frames_m = mrep.frames
        n = len(frames_m)
        idx = st.slider("Frame", 0, max(0, n - 1), 0, key="watch_multi_slider")
        fr = frames_m[idx]
        trails = trails_up_to(frames_m, idx) if show_trail else None
        rgb = multi_frame_to_rgb(fr, cell=int(cell), trails=trails)
        left, right = st.columns([1.4, 1])
        with left:
            st.image(rgb, caption=f"tick={fr.tick}", use_container_width=False)
        with right:
            st.markdown("**Agents**")
            for i, a in enumerate(fr.agents):
                st.write(
                    f"**[{i}] {a.genome_id}** · food={a.food_collected} · "
                    f"E={a.energy:.1f} · ({a.x},{a.y}) · {a.action_name()} · "
                    f"{'alive' if a.alive else 'dead'}"
                )
            if mrep.final:
                st.markdown("**Final scores**")
                st.dataframe(mrep.final, hide_index=True)
        if st.button("Save multi GIF", key="watch_multi_gif"):
            out = (
                artifacts
                / "replays"
                / f"multi_{int(seed)}_{int(datetime.now().timestamp())}.gif"
            )
            multi_replay_to_gif(
                mrep, out, cell=max(8, int(cell) - 4), duration_ms=int(speed)
            )
            st.success(f"Wrote {out}")
        return  # multi mode done

    # --- Live stream: paint as the sim runs ---
    if watch_mode == "single" and live_clicked:
        st.session_state["watch_playing"] = False
        stage = st.empty()
        status = st.empty()
        frames = []
        trail: set[tuple[int, int]] = set()
        death = "timeout"
        err = ""
        try:
            policy = _make_policy()
            status.info("Live streaming episode…")
            delay = max(0.0, float(speed) / 1000.0)
            for fr, done, death_s, err_s in iter_episode(
                policy,
                world,
                seed=int(seed),
                train_weights=False,
                episode_timeout_s=float(fit.episode_timeout_s or 30),
            ):
                if done and fr.action is None and frames and death_s in (
                    "timeout",
                    "timeout_wall",
                ):
                    death = death_s
                    err = err_s
                    break
                frames.append(fr)
                if err_s:
                    err = err_s
                if death_s:
                    death = death_s
                trail.add((int(fr.x), int(fr.y)))
                rgb = frame_to_rgb(
                    fr, cell=int(cell), trail=trail if show_trail else None
                )
                with stage.container():
                    left, right = st.columns([1.4, 1])
                    with left:
                        st.image(
                            rgb,
                            caption=f"LIVE tick={fr.tick}  {fr.action_name()}",
                            use_container_width=False,
                        )
                    with right:
                        st.metric("tick", fr.tick)
                        st.metric("energy", f"{fr.energy:.1f} / {fr.energy_max:.0f}")
                        st.progress(
                            min(1.0, max(0.0, fr.energy / max(1e-6, fr.energy_max)))
                        )
                        st.metric("position", f"({fr.x}, {fr.y})")
                        st.metric("action", fr.action_name())
                        st.metric("food", fr.food_collected)
                        st.metric("alive", "yes" if fr.alive else "no")
                if done:
                    break
                time_mod.sleep(delay)

            last = frames[-1] if frames else None
            summary = EpisodeSummary(
                seed=int(seed),
                score=0.0,
                food_collected=last.food_collected if last else 0,
                ticks_survived=last.tick if last else 0,
                final_energy=last.energy if last else 0.0,
                invalid_actions=sum(1 for f in frames if f.invalid),
                wall_bumps=sum(1 for f in frames if f.wall_bump),
                death_reason=death if not err else "error",
            )
            if not err:
                summary.score = episode_score(summary, fit)
            rep = EpisodeReplay(
                frames=frames,
                summary=summary,
                seed=int(seed),
                genome_id=genome_id,
                ablation=ablation,
                error=err,
            )
            st.session_state["watch_replay"] = rep
            st.session_state["watch_frame_idx"] = max(0, len(frames) - 1)
            st.session_state["watch_playing"] = False
            # Build animated GIF for browser video loop
            try:
                gif_path = artifacts / "replays" / "_last_watch_live.gif"
                gif_path.parent.mkdir(parents=True, exist_ok=True)
                replay_to_gif(
                    rep,
                    gif_path,
                    cell=max(8, int(cell) - 4),
                    duration_ms=int(speed),
                    show_trail=show_trail,
                )
                st.session_state["watch_gif_path"] = str(gif_path)
            except Exception:
                st.session_state.pop("watch_gif_path", None)
            if err:
                status.error(err)
            else:
                status.success(
                    f"Live stream done · {len(frames)} frames · "
                    f"food={summary.food_collected} · ticks={summary.ticks_survived} · "
                    f"death={summary.death_reason} · score={summary.score:.3f}"
                )
        except Exception as e:
            st.exception(e)

    if watch_mode == "single" and rec_clicked:
        try:
            with st.spinner("Recording episode on host…"):
                rep = record_episode(
                    _make_policy(),
                    world,
                    seed=int(seed),
                    train_weights=False,
                    episode_timeout_s=float(fit.episode_timeout_s or 30),
                    genome_id=genome_id,
                    ablation=ablation,
                    fit_cfg=fit,
                )
            st.session_state["watch_replay"] = rep
            st.session_state.pop("watch_multi_replay", None)
            st.session_state["watch_frame_idx"] = 0
            st.session_state["watch_playing"] = True  # autoplay after record
            if rep.error:
                st.error(rep.error)
            else:
                st.success(
                    f"Recorded {len(rep.frames)} frames · "
                    f"food={rep.summary.food_collected} · "
                    f"ticks={rep.summary.ticks_survived} · "
                    f"death={rep.summary.death_reason} · "
                    f"score={rep.summary.score:.3f}"
                )
                try:
                    gif_path = artifacts / "replays" / "_last_watch_live.gif"
                    gif_path.parent.mkdir(parents=True, exist_ok=True)
                    replay_to_gif(
                        rep,
                        gif_path,
                        cell=max(8, int(cell) - 4),
                        duration_ms=int(speed),
                        show_trail=show_trail,
                    )
                    st.session_state["watch_gif_path"] = str(gif_path)
                except Exception:
                    pass
        except Exception as e:
            st.exception(e)

    rep = st.session_state.get("watch_replay")
    if watch_mode != "single" or not rep or not getattr(rep, "frames", None):
        if watch_mode == "single":
            st.info(
                "Click **Live stream (video)** to watch the organism move in real time, "
                "or **Record only** then scrub / autoplay. Switch Mode to **multi** for "
                "several genomes on one map."
            )
        return

    frames = rep.frames
    n = len(frames)

    # Browser-native looping GIF (closest to a video player)
    gif_p = st.session_state.get("watch_gif_path")
    if gif_p and Path(gif_p).exists():
        st.markdown("#### Video loop (GIF)")
        st.image(str(gif_p), caption="Auto-playing GIF — loops in the browser")
        with open(gif_p, "rb") as fh:
            st.download_button(
                "Download GIF",
                data=fh.read(),
                file_name=Path(gif_p).name,
                mime="image/gif",
                key="watch_dl_gif",
            )

    st.markdown("#### Frame scrubber / replay")
    play = st.toggle(
        "Autoplay scrubber",
        value=bool(st.session_state.get("watch_playing")),
        key="watch_play_tog",
    )
    st.session_state["watch_playing"] = play
    loop = st.checkbox("Loop autoplay", value=False, key="watch_loop")

    run_every = timedelta(milliseconds=int(speed)) if play else None

    @st.fragment(run_every=run_every)
    def _player() -> None:
        idx = int(st.session_state.get("watch_frame_idx", 0))
        if st.session_state.get("watch_playing") and n > 0:
            nxt = idx + 1
            if nxt >= n:
                if loop:
                    nxt = 0
                else:
                    nxt = n - 1
                    st.session_state["watch_playing"] = False
            st.session_state["watch_frame_idx"] = nxt
            idx = nxt

        idx = st.slider("Frame", 0, max(0, n - 1), idx, key="watch_slider")
        st.session_state["watch_frame_idx"] = idx
        fr = frames[idx]
        trail = trail_up_to(frames, idx) if show_trail else None
        rgb = frame_to_rgb(fr, cell=int(cell), trail=trail)

        left, right = st.columns([1.4, 1])
        with left:
            st.image(
                rgb,
                caption=f"tick={fr.tick}  action={fr.action_name()}",
                use_container_width=False,
            )
        with right:
            st.metric("tick", fr.tick)
            st.metric("energy", f"{fr.energy:.1f} / {fr.energy_max:.0f}")
            st.progress(min(1.0, max(0.0, fr.energy / max(1e-6, fr.energy_max))))
            st.metric("position", f"({fr.x}, {fr.y})")
            st.metric("action", fr.action_name())
            st.metric("reward", f"{fr.reward:.3f}")
            st.metric("food collected", fr.food_collected)
            st.metric("alive", "yes" if fr.alive else "no")
            s = rep.summary
            st.markdown("**Episode summary**")
            st.write(
                {
                    "genome": rep.genome_id,
                    "ablation": rep.ablation,
                    "seed": rep.seed,
                    "score": round(s.score, 4),
                    "food": s.food_collected,
                    "ticks": s.ticks_survived,
                    "death": s.death_reason,
                    "invalid": s.invalid_actions,
                    "wall_bumps": s.wall_bumps,
                }
            )

    _player()

    st.markdown("#### Export")
    if st.button("Save GIF to artifacts/replays/", key="watch_gif"):
        out_dir = artifacts / "replays"
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"watch_{rep.genome_id}_{rep.seed}_{int(datetime.now().timestamp())}.gif"
        path = out_dir / name
        try:
            replay_to_gif(
                rep,
                path,
                cell=max(8, int(cell) - 4),
                duration_ms=int(speed),
                show_trail=show_trail,
            )
            st.session_state["watch_gif_path"] = str(path)
            st.success(f"Wrote {path}")
            st.rerun()
        except Exception as e:
            st.error(str(e))


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
            "Watch",
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
    elif page == "Watch":
        page_watch(artifacts, db)
    elif page == "Run":
        page_run(artifacts, db)
    elif page == "Genomes":
        page_genomes(artifacts, db)
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
