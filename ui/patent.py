"""Patent card and triage report."""

import altair as alt
import pandas as pd
import streamlit as st

from graveyard import config, db, gp, orchestrator

from . import common, style


def _citation_chart(patent: dict):
    by_year = patent["metrics"]["fwd_by_year"]
    if not by_year:
        st.caption("No later patents cite this one.")
        return
    df = pd.DataFrame({"year": [int(y) for y in by_year], "citations": list(by_year.values())})
    bars = alt.Chart(df).mark_bar(color="#5b8def").encode(
        x=alt.X("year:O", title="Priority year of the citing filing"),
        y=alt.Y("citations:Q", title="Citing filings"),
        tooltip=["year", "citations"],
    )
    layers = [bars]
    end = patent["facts"].get("end_year")
    if end:
        rule = alt.Chart(pd.DataFrame({"year": [end]})).mark_rule(color="#d9534f", strokeDash=[4, 3], size=2).encode(x="year:O")
        label = "lapsed" if patent["status"] == "lapsed_fees" else "expired"
        text = alt.Chart(pd.DataFrame({"year": [end], "t": [f"{label} {end}"]})).mark_text(
            align="left", dx=4, dy=-6, color="#d9534f").encode(x="year:O", text="t", y=alt.value(10))
        layers += [rule, text]
    st.altair_chart(alt.layer(*layers).properties(height=220), use_container_width=True)


def _card(patent: dict):
    f, m, rec = patent["facts"], patent["metrics"], patent["record"]
    st.markdown(f"{common.status_badge(patent['status'])} {common.badge(patent['tech_label'], 'blue')} "
                f"{common.badge('CPC ' + (patent['cpc_first'] or '?'), 'gray')}")
    st.caption(f"[{patent['pub']} on Google Patents]({gp.patent_url(patent['pub'])}) · "
               f"Owner: {patent['assignee'] or 'unknown'} · Inventors: {', '.join(rec.get('inventors', [])[:3]) or 'unknown'}")
    c = st.columns(2) + st.columns(2)
    c[0].metric("Priority", f["priority_date"] or "?")
    c[1].metric("Granted", f["grant_date"] or "?")
    if patent["status"] == "lapsed_fees":
        c[2].metric("Lapsed", f["lapse_date"] or "?", help=f["lapse_source"])
        c[3].metric("Fee window", f"{f['fee_window']}th year" if f["fee_window"] else "?",
                    help="Fees are due 3.5, 7.5 and 11.5 years after grant")
    else:
        c[2].metric("Term ended", f["term_end"] or "?", help="Estimated as filing date + 20 years" if f["term_end_estimated"] else None)
        c[3].metric("Fees paid", ", ".join(f"{y}th" for y in f["fees_paid"]) or "none")
    if f.get("status_inferred"):
        st.caption(f":material/info: {f['status_inferred']}")
    src = rec.get("source")
    if src and "archive" in src:
        st.caption(f"Record retrieved from an Internet Archive {src.split('web.archive.org ')[-1][:17]} of the Google Patents page.")
    st.markdown("**Abstract**")
    st.write(patent["abstract"] or "_No abstract on record._")
    with st.expander("First claim"):
        st.write(rec.get("claims", {}).get("first") or "_No claims on record._")
    st.markdown("**Who cited it, and when**")
    _citation_chart(patent)
    c = st.columns(3)
    c[0].metric("Cited by", m["fwd_total"])
    c[1].metric("Cited after it died (others)", m["fwd_after_end_unrelated"])
    c[2].metric(f"Cited since {config.RECENT_SINCE}", m["fwd_recent"],
                help=f"Citing filings with a priority date in the last {config.RECENT_YEARS} years")


def _ev_chips(ids: list[str]) -> str:
    return " ".join(common.badge(i, "violet") for i in ids)


def _report_markdown(out: dict) -> str:
    r = out["report"]
    lines = [f"# Triage report: {out['pub']}", f"**{out['title']}**", "",
             f"> {config.DISCLAIMER}", "",
             f"**Revival score:** {r['score']}/100 ({r['confidence']} confidence) - {r['verdict']}", "",
             r["headline"], "", "## What it is", r["what_it_is"], "", "## Why it died",
             f"{r['why_it_died']['text']} [{', '.join(r['why_it_died']['evidence'])}]", "", "## Case for"]
    lines += [f"- {p['point']} [{', '.join(p['evidence'])}]" for p in r["case_for"]]
    lines += ["", "## Case against"] + [f"- {p['point']} [{', '.join(p['evidence'])}]" for p in r["case_against"]]
    read = (out.get("market") or {}).get("read") or {}
    if read.get("signals") or read.get("market_read"):
        lines += ["", "## Commercial evidence", read.get("market_read", "")]
        lines += [f"- ({s['confidence']} confidence) {s['signal']} [{', '.join(s['evidence'])}]" for s in read.get("signals", [])]
    lines += ["", "## What could still block use"]
    lines += [f"- ({b['severity']}) {b['point']} [{', '.join(b['evidence'])}]" for b in r["blockers"]]
    a = r["assumption_to_test"]
    lines += ["", "## The one assumption to test first", f"**{a['assumption']}**", "", f"Why: {a['why_riskiest']}",
              "", f"How to test: {a['how_to_test']}", "", "## Questions for a registered patent attorney"]
    lines += [f"- {q}" for q in r["attorney_questions"]]
    lines += ["", "## Evidence"] + [f"- {e['id']} ({e['agent']}, {e['confidence']}): {e['claim']} Source: {e['source']}. "
                                    f"Method: {e['method']}." for e in out["evidence"]]
    lines += ["", f"_Generated {out['generated_at']} as of {out['as_of']}. {'Model: ' + out['model'] if out['model'] else 'Rule-based report.'}_"]
    return "\n".join(lines)


_esc = common.esc


def _report(out: dict):
    r = _esc(out["report"])
    common.legal_notice()
    with st.container(border=True):
        head = st.columns([1, 3], vertical_alignment="center")
        with head[0]:
            st.html(style.ring(out["report"]["score"], 96))
            st.markdown(f"{common.badge(r['confidence'] + ' confidence', common.CONF_COLOR[r['confidence']])}")
        with head[1]:
            st.markdown(f"### :{common.score_color(r['score'])}[{r['verdict']}]")
            st.markdown(r["headline"])

    comps = out["market"]["score"]["components"]
    df = pd.DataFrame([{"signal": c["label"], "points": c["points"], "max": c["weight"]} for c in comps.values()])
    base = alt.Chart(df).encode(y=alt.Y("signal:N", sort=None, title=None))
    chart = alt.layer(
        base.mark_bar(color="#e6e6e6").encode(x=alt.X("max:Q", title="Points toward the revival score")),
        base.mark_bar(color="#5b8def").encode(x="points:Q", tooltip=["signal", "points", "max"]),
    ).properties(height=190)
    with st.expander("Score breakdown: how the code computed this score", expanded=False):
        st.altair_chart(chart, use_container_width=True)
        st.caption("Each signal is computed from public records and scaled 0 to 1, then weighted. "
                   "Confidence reflects how much evidence the score rests on.")

    st.markdown("#### What it is")
    st.write(r["what_it_is"])
    st.markdown("#### Why it died")
    st.markdown(f"{r['why_it_died']['text']} {_ev_chips(r['why_it_died']['evidence'])}")

    c = st.columns(2)
    with c[0]:
        st.markdown("#### Case for building on it")
        for p in r["case_for"] or [{"point": "_No supporting evidence found._", "evidence": []}]:
            st.markdown(f"- {p['point']} {_ev_chips(p['evidence'])}")
    with c[1]:
        st.markdown("#### Case against")
        for p in r["case_against"] or [{"point": "_No evidence against found._", "evidence": []}]:
            st.markdown(f"- {p['point']} {_ev_chips(p['evidence'])}")

    read = _esc((out.get("market") or {}).get("read") or {})
    web = _esc((out.get("market") or {}).get("web") or [])
    if read.get("signals") or read.get("market_read") or read.get("who_is_active") or web:
        st.markdown("#### Commercial evidence")
        if read.get("market_read"):
            st.markdown(read["market_read"])
        for s in read.get("signals", []):
            st.markdown(f"- {common.badge(s['confidence'] + ' confidence', common.CONF_COLOR.get(s['confidence'], 'gray'))} "
                        f"{s['signal']} {_ev_chips(s['evidence'])}")
        if web:
            st.markdown("**Found on the web today**")
            for w in web:
                st.markdown(f"- {common.badge(w['confidence'] + ' confidence', common.CONF_COLOR.get(w['confidence'], 'gray'))} "
                            f"{w['finding']} [source]({w['url']}) {_ev_chips([w['evidence']])}")
        if read.get("who_is_active"):
            st.caption(f"Who is active: {read['who_is_active']}")

    st.markdown("#### What could still block use")
    for b in r["blockers"]:
        st.markdown(f"- {common.badge(b['severity'], common.SEV_COLOR.get(b['severity'], 'gray'))} {b['point']} {_ev_chips(b['evidence'])}")
    detail = (out.get("blockers") or {}).get("blockers", [])
    items = [dict(i, blocker=b["title"]) for b in detail for i in b.get("items", [])]
    if items:
        with st.expander(f"Candidate blocking patents ({len(items)})"):
            st.dataframe(pd.DataFrame([{
                "blocker": i["blocker"], "patent": gp.patent_url(i["pub"]), "title": i.get("title"),
                "priority": i.get("priority_date"), "owner": i.get("assignee"),
                "overlap": i.get("overlap"), "why": i.get("reason"), "status": i.get("known_status") or i.get("status") or "unverified",
            } for i in items]), column_config={"patent": st.column_config.LinkColumn(display_text=r"patent/(.*?)/en")},
                hide_index=True, use_container_width=True)

    a = r["assumption_to_test"]
    with st.container(border=True):
        st.markdown("#### :material/science: The one assumption to test first")
        st.markdown(f"**{a['assumption']}**")
        st.markdown(f"_Why it is the riskiest:_ {a['why_riskiest']}")
        st.markdown(f"_How to test it:_ {a['how_to_test']}")

    st.markdown("#### Questions for a registered patent attorney")
    for q in r["attorney_questions"]:
        st.markdown(f"- {q}")

    near = (out.get("nearby") or {}).get("items", [])
    if near:
        st.markdown("#### Other dead patents nearby")
        for n in near:
            cols = st.columns([6, 1])
            cols[0].markdown(f"{n['title'][:90]} · `{n['pub']}` · {common.status_badge(n['status'])} "
                             f"{common.badge(str(n['score']), common.score_color(n['score']))}")
            if cols[1].button("Open", key=f"near_{n['pub']}"):
                common.open_patent(n["pub"])

    with st.expander(f"Evidence ({len(out['evidence'])} records)", expanded=False):
        st.dataframe(pd.DataFrame([{
            "id": e["id"], "agent": e["agent"], "finding": e["claim"], "confidence": e["confidence"],
            "method": e["method"], "source": e["source"]} for e in out["evidence"]]),
            column_config={"source": st.column_config.LinkColumn()}, hide_index=True, use_container_width=True)

    with st.expander("Show your work: agent trace", expanded=False):
        st.dataframe(pd.DataFrame([{"agent": s["agent"], "task": s["task"], "status": s["status"],
                                    "result": s.get("summary"), "seconds": s.get("seconds")} for s in out["trace"]]),
                     hide_index=True, use_container_width=True)
        u = out["usage"]
        if u["calls"]:
            st.dataframe(pd.DataFrame(u["calls"]), hide_index=True, use_container_width=True)
            st.caption(f"Model cost for this report: ${u['total_cost_usd']:.3f} over {len(u['calls'])} Claude calls, "
                       f"{u['seconds']}s end to end.")
        else:
            st.caption("This report was written by the rule-based fallback (no Claude calls).")
        if r.get("verifier_log"):
            st.markdown("**Verifier changes**")
            for line in r["verifier_log"]:
                st.markdown(f"- {line}")

    st.download_button("Download report (Markdown)", _report_markdown(out), file_name=f"{out['pub']}_triage.md",
                       icon=":material/download:")
    st.caption(f"Generated {out['generated_at'][:16].replace('T', ' ')} UTC, data as of {out['as_of']}"
               + (f", model {out['model']}." if out["model"] else ", rule-based."))


def page():
    con = common.con()
    pub = st.query_params.get("pub") or st.session_state.get("pub")
    if not pub:
        st.title("Patent report")
        rows = db.search(con, limit=500)
        if not rows:
            st.error("The patent database is empty.")
            return
        pub = st.selectbox("Pick a patent", [r["pub"] for r in rows],
                           format_func=lambda p: next(f"{r['pub']} · {r['title'][:80]}" for r in rows if r["pub"] == p))
    patent = db.get(con, pub)
    if not patent:
        st.error(f"{pub} is not in the sample.")
        return
    st.session_state["pub"] = pub

    if st.button(":material/arrow_back: Back to the marketplace"):
        st.switch_page(common.PAGES["market"])
    st.title(patent["title"])

    left, right = st.columns([5, 6], gap="large")
    with left:
        _card(patent)
    with right:
        st.subheader("Triage report")
        live = common.live_allowed()
        # Rule-based runs (no passcode) live in this session only, so they never replace a saved report
        out = orchestrator.cached(pub) or st.session_state.get(f"rules_{pub}")
        if live or not (out and out["report"]["mode"] == "claude"):
            run_label = ("Re-run the agents" if out else "Run the triage agents") + ("" if live else " (rule-based)")
            if st.button(run_label, type="primary" if not out else "secondary", icon=":material/smart_toy:"):
                with st.status("Running the agents...", expanded=True) as box:
                    def on_step(step):
                        if step["status"] == "running":
                            box.write(f"**{step['agent']}**: {step['task']}")
                        else:
                            box.write(f"↳ {step.get('summary') or step['status']} ({step.get('seconds', 0)}s)")
                    out = orchestrator.run(con, pub, on_step=on_step, use_llm=live, save=live)
                    box.update(label=f"Done in {out['usage']['seconds']}s", state="complete", expanded=False)
                if live:
                    common.count_live_run()
                else:
                    st.session_state[f"rules_{pub}"] = out
        common.mode_caption()
        if out:
            _report(out)
        else:
            st.markdown("Five agents read the public record for this patent: **Scout** finds similar dead patents, "
                        "**Status** confirms how it died, **Blocker** checks what could still stop you, **Market** "
                        "weighs the commercial evidence and scores it, and **Report** writes it up with the one "
                        "assumption to test first.")
