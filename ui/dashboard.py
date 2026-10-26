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

from . import common, style


def _when(item: dict) -> str:
    d = date.fromisoformat(item["date"])
    return d.strftime("%b %Y") if item.get("date_precision") == "month" else d.strftime("%b %d, %Y")


def _news_item(i: dict, compact: bool = False):
    style.news_card(i, _when(i), compact)


def _patents(con) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in con.execute(
        "SELECT pub, title, tech_class, tech_label, status, end_year, score, verdict, fwd_recent FROM patents")])


# ---------------------------------------------------------------- Overview


def _overview(df: pd.DataFrame, events: list[dict]):
    since, n = config.RECENT_SINCE, len(df)
    future, built_on = int((df.score >= 60).sum()), int((df.fwd_recent >= 3).sum())
    lapsed, expired = int((df.status == "lapsed_fees").sum()), int((df.status == "expired_term").sum())
    style.stat_cards([
        dict(label="Dead patents tracked", value=n, icon="deceased", color=style.BLUE,
             caption=f"{lapsed} lapsed for unpaid fees · {expired} expired at full term", share=lapsed / n),
        dict(label="Dead patents with a future", value=future, icon="trending_up", color=style.TEAL,
             caption=f"{future / n:.0%} score 60 or more for revival", share=future / n),
        dict(label="Still being built on", value=built_on, icon="construction", color=style.VIOLET,
             caption=f"{built_on / n:.0%} cited by 3+ filings since {since}", share=built_on / n),
        dict(label="Deals and events tracked", value=len(events), icon="handshake", color=style.AMBER,
             caption="Last 18 months, each linked to its source"),
    ])

    left, right = st.columns([3, 2], gap="medium")
    with left.container(border=True):
        style.card_title("monitoring", "Where dead patents are still being built on", style.TEAL,
                         f"Filings since {since} that cite a dead patent in each field (top 10)")
        by = (df.groupby(["tech_class", "tech_label"])
                .agg(filings=("fwd_recent", "sum"), patents=("pub", "count")).reset_index()
                .sort_values("filings", ascending=False).head(10))
        by["field"] = by["tech_label"].fillna(by["tech_class"])
        chart = alt.Chart(by).mark_bar(cornerRadiusEnd=5, height=18).encode(
            y=alt.Y("field:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240, labelColor="#334155")),
            x=alt.X("filings:Q", title=f"Citing filings since {since}",
                    axis=alt.Axis(grid=True, gridColor="#EEF2F7", labelColor="#64748B", titleColor="#64748B")),
            color=alt.Color("filings:Q", scale=alt.Scale(range=["#99F6E4", "#0F766E"]), legend=None),
            tooltip=[alt.Tooltip("field:N", title="Field"), alt.Tooltip("filings:Q", title="Citing filings"),
                     alt.Tooltip("patents:Q", title="Dead patents in sample")],
        ).properties(height=30 * len(by), background="transparent").configure_view(stroke=None)
        st.altair_chart(chart, use_container_width=True)
    with right.container(border=True):
        style.card_title("bolt", "Latest deals and events", style.AMBER, "Newest first; more in the Deals & news tab")
        for i in events[:5]:
            _news_item(i, compact=True)

    style.section("Top opportunities", "Highest revival scores in the graveyard; saved reports open instantly")
    top = df.sort_values("score", ascending=False).head(6).to_dict("records")
    grid = st.columns(3, gap="small")
    for k, r in enumerate(top):
        with grid[k % 3].container(border=True):
            ready = orchestrator.report_path(r["pub"]).exists()
            style.opp_header(r["score"], r["title"][:85], f"{r['pub']} · {r['tech_label'] or r['tech_class']} · ended {r['end_year']}")
            st.markdown(f"{common.status_badge(r['status'])}" + (f" {common.badge('report ready', 'violet')}" if ready else ""))
            if st.button("Open report", key=f"dash_open_{r['pub']}", use_container_width=True, icon=":material/arrow_forward:"):
                common.open_patent(r["pub"])


# ---------------------------------------------------------------- Simulation Lab


def _render_simulation(out: dict):
    b = common.esc(out["brief"])
    common.legal_notice()
    st.markdown(f"**{b['summary']}**")
    if b.get("white_space"):
        st.caption(f"White space: {b['white_space']}")

    cols = st.columns(3, gap="small")
    with cols[0].container(border=True):
        style.card_title("bar_chart", "Market opportunity", style.BLUE, "Size, growth and players, from the web")
        if out["market"]:
            for m in common.esc(out["market"]):
                st.markdown(f"- {common.badge(m['confidence'], common.CONF_COLOR.get(m['confidence'], 'gray'))} "
                            f"{m['finding']} [source]({m['url']})")
        else:
            st.caption("No web search in this run (needs Claude and the team passcode on the hosted app).")
    with cols[1].container(border=True):
        style.card_title("travel_explore", "Patent landscape", style.VIOLET, "Dead patents that already solve part of this")
        for g in out["graveyard"]:
            st.markdown(f"- [{g['pub']}]({gp.patent_url(g['pub'])}) {common.esc(g['title'][:70])} "
                        f"{common.badge(str(g['score']), common.score_color(g['score']))}")
        st.caption("Closest earlier patents")
        for x in out["landscape"][:6]:
            color = "red" if x["standing"] == "may still be in force" else "gray"
            st.markdown(f"- [{x['pub']}]({gp.patent_url(x['pub'])}) {common.esc(x['title'][:60])} "
                        f"{common.badge(x['standing'], color)}")
    with cols[2].container(border=True):
        style.card_title("route", "Strategic pathways", style.TEAL, "Each one tied to evidence")
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
    grid = st.columns(2, gap="small")
    for k, i in enumerate(items):
        with grid[k % 2].container(border=True):
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
    df = _patents(con)
    if df.empty:
        st.error("The patent database is empty.")
        return
    events = news.all_items()
    reports = len(list(config.REPORTS_DIR.glob("*.json")))
    style.hero(
        "Innovation intelligence · " + config.PRODUCT_NAME,
        "Find the dead patents worth building on",
        "AI agents scan lapsed and expired US patents, score which ones have a future, and show what could "
        "still stand in the way. Research and triage, not legal advice.",
        [f"<b>{len(df)}</b> dead patents", f"<b>{df.tech_class.nunique()}</b> technology fields",
         f"<b>{reports}</b> agent reports", f"<b>{len(events)}</b> deals tracked",
         f"Data as of {config.AS_OF.strftime('%b %d, %Y')}"],
        ticker=events[:14])
    tabs = st.tabs([":material/insights: Overview", ":material/science: Simulation Lab", ":material/handshake: Deals & news"])
    with tabs[0]:
        _overview(df, events)
    with tabs[1]:
        _simulation(con)
    with tabs[2]:
        _deals(con)
