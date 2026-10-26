"""Innovation dashboard: three tabs (Overview, Simulation Lab, Deals & news).

Every number here is computed from our patent data, and every deal or market figure comes
from a page Claude found on the web, shown with its date and source.
"""

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from graveyard import classes, config, gp, llm, orchestrator
from graveyard.agents import news, simulate

from . import common

TYPE_COLOR = {"M&A": "blue", "Licensing": "green", "Partnership": "violet", "Regulatory": "orange",
              "Litigation": "red", "Funding": "gray"}


def _when(item: dict) -> str:
    d = date.fromisoformat(item["date"])
    return d.strftime("%b %Y") if item.get("date_precision") == "month" else d.strftime("%b %d, %Y")


def _news_item(i: dict, compact: bool = False):
    i = common.esc(i)
    st.markdown(f"{common.badge(i['type'], TYPE_COLOR.get(i['type'], 'gray'))} "
                f"<span style='opacity:0.7;font-size:0.85rem'>{_when(i)} · {i['field_label']}</span>",
                unsafe_allow_html=True)
    st.markdown(f"**[{i['headline']}]({i['url']})**")
    if not compact:
        st.caption(f"{i['summary']}  \n{', '.join(i['companies'])}{' · ' if i['companies'] else ''}Source: {i['source']}")


# ---------------------------------------------------------------- Overview


def _overview(con):
    rows = [dict(r) for r in con.execute(
        "SELECT pub, title, tech_class, tech_label, status, end_year, score, verdict, fwd_recent FROM patents")]
    if not rows:
        st.error("The patent database is empty.")
        return
    df = pd.DataFrame(rows)
    events = news.all_items()
    since = config.RECENT_SINCE

    c = st.columns(4)
    tiles = [
        ("Dead patents", f"{len(df)}",
         f"{(df.status == 'lapsed_fees').sum()} lapsed for unpaid fees, {(df.status == 'expired_term').sum()} expired at full term"),
        ("With a future", f"{(df.score >= 60).sum()}", "Revival score of 60 or more"),
        ("Still built on", f"{(df.fwd_recent >= 3).sum()}", f"Cited by 3 or more filings since {since}"),
        ("Deals tracked", f"{len(events)}", "Found by Claude web search, each with a source"),
    ]
    for col, (label, value, help_text) in zip(c, tiles):
        with col.container(border=True):
            st.metric(label, value)
            st.caption(help_text)

    st.markdown("#### Where dead patents are still being built on")
    st.caption(f"Filings since {since} that cite a dead patent in each field, from the citation records of our "
               f"{len(df)} patents. Top 10 fields.")
    by = (df.groupby(["tech_class", "tech_label"])
            .agg(filings=("fwd_recent", "sum"), patents=("pub", "count")).reset_index()
            .sort_values("filings", ascending=False).head(10))
    by["field"] = by["tech_label"].fillna(by["tech_class"])
    chart = alt.Chart(by).mark_bar(color="#5b8def", cornerRadiusEnd=4, height=16).encode(
        y=alt.Y("field:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X("filings:Q", title=f"Citing filings since {since}", axis=alt.Axis(grid=True, gridOpacity=0.15)),
        tooltip=[alt.Tooltip("field:N", title="Field"), alt.Tooltip("filings:Q", title="Citing filings"),
                 alt.Tooltip("patents:Q", title="Dead patents in sample")],
    ).properties(height=34 * len(by))
    st.altair_chart(chart, use_container_width=True)

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("#### Top opportunities")
        st.caption("Highest revival scores in the graveyard. A saved report opens instantly.")
        top = df.sort_values("score", ascending=False).head(6).to_dict("records")
        grid = st.columns(2)
        for k, r in enumerate(top):
            with grid[k % 2].container(border=True):
                ready = orchestrator.report_path(r["pub"]).exists()
                st.markdown(f"{common.status_badge(r['status'])} {common.badge(str(r['score']) + '/100', common.score_color(r['score']))}"
                            + (f" {common.badge('report ready', 'violet')}" if ready else ""))
                st.markdown(f"**{r['title'][:80]}**")
                st.caption(f"{r['pub']} · {r['tech_label'] or r['tech_class']} · ended {r['end_year']}")
                if st.button("Open", key=f"dash_open_{r['pub']}", use_container_width=True):
                    common.open_patent(r["pub"])
    with right:
        st.markdown("#### Latest deals and events")
        st.caption("Most recent across all fields. More in the Deals & news tab.")
        for i in events[:5]:
            with st.container(border=True):
                _news_item(i, compact=True)


# ---------------------------------------------------------------- Simulation Lab


def _render_simulation(out: dict):
    b = common.esc(out["brief"])
    common.legal_notice()
    st.markdown(f"**{b['summary']}**")
    if b.get("white_space"):
        st.caption(f"White space: {b['white_space']}")

    cols = st.columns(3, gap="medium")
    with cols[0].container(border=True):
        st.markdown("##### :material/bar_chart: Market opportunity")
        if out["market"]:
            for m in common.esc(out["market"]):
                st.markdown(f"- {common.badge(m['confidence'], common.CONF_COLOR.get(m['confidence'], 'gray'))} "
                            f"{m['finding']} [source]({m['url']})")
        else:
            st.caption("No web search in this run (needs Claude and the team passcode on the hosted app).")
    with cols[1].container(border=True):
        st.markdown("##### :material/search: Patent landscape")
        st.caption("Dead patents that already solve part of this")
        for g in out["graveyard"]:
            st.markdown(f"- [{g['pub']}]({gp.patent_url(g['pub'])}) {common.esc(g['title'][:70])} "
                        f"{common.badge(str(g['score']), common.score_color(g['score']))}")
        st.caption("Closest earlier patents")
        for x in out["landscape"][:6]:
            color = "red" if x["standing"] == "may still be in force" else "gray"
            st.markdown(f"- [{x['pub']}]({gp.patent_url(x['pub'])}) {common.esc(x['title'][:60])} "
                        f"{common.badge(x['standing'], color)}")
    with cols[2].container(border=True):
        st.markdown("##### :material/route: Strategic pathways")
        for p in b["pathways"]:
            st.markdown(f"**{p['name']}**  \n{p['detail']}")

    a = b["assumption_to_test"]
    with st.container(border=True):
        st.markdown("#### :material/science: The one assumption to test first")
        st.markdown(f"**{a['assumption']}**")
        st.markdown(f"_How to test it:_ {a['how_to_test']}")
    with st.expander("Questions for a registered patent attorney"):
        for q in b["attorney_questions"]:
            st.markdown(f"- {q}")
    with st.expander(f"Evidence ({len(out['evidence'])} records)"):
        st.dataframe(pd.DataFrame([{"id": e["id"], "agent": e["agent"], "finding": e["claim"], "confidence": e["confidence"],
                                    "source": e["source"]} for e in out["evidence"]]),
                     column_config={"source": st.column_config.LinkColumn()}, hide_index=True, use_container_width=True)
    st.caption(f"Generated {out['generated_at'][:16].replace('T', ' ')} UTC · "
               + (f"model {out['model']} · cost ${out['cost_usd']:.2f}" if out.get("model") else "rule-based, no Claude calls"))


def _simulation(con):
    st.markdown("Describe an idea. The same agents check what dead patents already cover it, which earlier patents "
                "may still be in force, what the market looks like, and which assumption to test first.")
    common.disclosure_notice()
    idea = st.text_area("Your idea, target market or technology angle", height=110, key="sim_idea",
                        placeholder=f"Example: {simulate.EXAMPLE_IDEA}")
    ok = st.checkbox("This is a public idea or one that is already protected.", key="sim_ok")
    live = common.live_allowed()
    if st.button("Run simulation" + ("" if live else " (rule-based)"), type="primary", icon=":material/science:",
                 disabled=not (ok and idea.strip())):
        with st.status("Running the agents on your idea...", expanded=True) as box:
            out = simulate.run(con, idea.strip(), llm.Usage(), use_llm=live, on_step=box.write)
            box.update(label="Simulation done", state="complete", expanded=False)
        if live:
            common.count_live_run()
        st.session_state["sim_out"] = out
    common.mode_caption()

    out = st.session_state.get("sim_out")
    if not out:
        out = simulate.load_example()
        if not out:
            return
        st.info(f"Showing a saved example run for a public idea: _{out['idea']}_", icon=":material/play_circle:")
    _render_simulation(out)


# ---------------------------------------------------------------- Deals & news


def _deals(con):
    data = news.load()
    fields = {code: f["label"] for code, f in data.get("fields", {}).items() if f["items"]}
    if not fields:
        st.info("No deals or events saved yet. Run `python scripts/refresh_news.py`.")
        return
    c = st.columns([3, 3])
    picked = c[0].multiselect("Fields", list(fields), format_func=lambda k: fields[k], placeholder="All fields")
    kinds = c[1].pills("Type", news.TYPES, selection_mode="multi")
    items = [i for i in news.all_items(picked or None) if not kinds or i["type"] in kinds]
    st.caption(f"{len(items)} events from the last 18 months, found by Claude web search and linked to their source. "
               "Verify details at the source before relying on them.")
    for i in items:
        with st.container(border=True):
            _news_item(i)

    if common.live_allowed():
        with st.expander("Refresh a field (one live web search, about $0.30)"):
            code = st.selectbox("Field", list(classes.TECH_CLASSES), format_func=classes.label, key="news_field")
            if st.button("Refresh", key="news_refresh"):
                usage = llm.Usage()
                with st.spinner(f"Searching for recent events in {classes.label(code)}..."):
                    items = news.fetch(classes.label(code), code, usage)
                news.save_field(code, classes.label(code), items, usage.total_cost)
                common.count_live_run()
                st.success(f"Found {len(items)} events (${usage.total_cost:.2f}).")
                st.rerun()


def page():
    con = common.con()
    st.title("Innovation dashboard")
    st.caption(f"{config.PRODUCT_NAME} · patent data as of {config.AS_OF.strftime('%b %d, %Y')}")
    tabs = st.tabs([":material/insights: Overview", ":material/science: Simulation Lab", ":material/handshake: Deals & news"])
    with tabs[0]:
        _overview(con)
    with tabs[1]:
        _simulation(con)
    with tabs[2]:
        _deals(con)
