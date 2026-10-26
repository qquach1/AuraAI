"""Marketplace: search and filter the patent graveyard."""

import streamlit as st

from graveyard import config, db, llm, orchestrator
from graveyard.agents import scout

from . import common, style


@st.cache_data(show_spinner="Scout is expanding your search...")
def _expand(query: str) -> dict:
    return scout.expand(query, llm.Usage())


def page():
    con = common.con()
    stats = db.stats(con)
    if not stats["total"]:
        st.error("The patent database is empty. Run `python scripts/build_sample.py` to pull the sample.")
        return

    lapsed = sum(r["n"] for r in stats["rows"] if r["status"] == "lapsed_fees")
    expired = sum(r["n"] for r in stats["rows"] if r["status"] == "expired_term")
    n_classes = len({r["tech_class"] for r in stats["rows"]})
    style.hero("Marketplace · " + config.PRODUCT_NAME, "Search the patent graveyard", config.TAGLINE,
               [f"<b>{stats['total']}</b> dead patents", f"<b>{lapsed}</b> lapsed for unpaid fees",
                f"<b>{expired}</b> expired at full term", f"<b>{n_classes}</b> technology fields"])

    with st.sidebar:
        st.subheader("Filters")
        labels = db.class_labels(con)
        counts = {}
        for r in stats["rows"]:
            counts[r["tech_class"]] = counts.get(r["tech_class"], 0) + r["n"]
        present = sorted(labels, key=lambda c: -counts.get(c, 0))
        picked = st.multiselect("Technology class", present,
                                format_func=lambda c: f"{c} · {labels.get(c) or c} ({counts.get(c, 0)})")
        reason = st.pills("Why it died", ["Lapsed: unpaid fees", "Expired: full term"], selection_mode="multi")
        lo, hi = stats["year_min"] or 2005, stats["year_max"] or config.AS_OF.year
        years = st.slider("Year it died", lo, hi, (lo, hi)) if lo < hi else (lo, hi)
        min_score = st.slider("Minimum revival score", 0, 100, 0, step=5)
        live = common.live_allowed()
        use_llm = st.toggle("Scout expands my search with Claude", value=live, disabled=not live,
                            help=None if live else "Needs the team passcode on the hosted app")

    statuses = [s for s, label in common.STATUS_LABEL.items() if label in (reason or [])] or ["lapsed_fees", "expired_term"]
    query = st.text_input("Search the graveyard", placeholder="e.g. wearable glucose sensor, wind turbine blade de-icing, "
                          "battery thermal runaway", help=config.DISCLOSURE_WARNING)
    if query:
        st.caption(":material/visibility: Anything you type counts as disclosed. Search with public terms, not your unprotected idea.")

    expansion = _expand(query) if query and use_llm else None
    res = scout.search(con, query, picked or None, statuses, years, min_score, use_llm=use_llm, expansion=expansion)
    rows = res["rows"]
    if res["expansion"]["terms"]:
        st.caption("Scout also searched for: " + ", ".join(res["expansion"]["terms"]))
    head = st.columns([3, 2])
    sorts = {"Best match" if query else "Revival score": None,
             "Revival score": lambda r: -r["score"],
             "Cited after it died": lambda r: -r["fwd_after_end_unrelated"],
             f"Cited since {config.RECENT_SINCE}": lambda r: -(r["fwd_recent"] or 0),
             "Died most recently": lambda r: -(r["end_year"] or 0)}
    order = head[1].selectbox("Sort by", list(sorts), label_visibility="collapsed")
    if sorts[order]:
        rows = sorted(rows, key=sorts[order])
    head[0].markdown(f"**{len(rows)} patents** · sorted by {order.lower()}")

    cols = st.columns(3, gap="small")
    for i, r in enumerate(rows[:60]):
        with cols[i % 3].container(border=True):
            style.opp_header(r["score"], r["title"][:110],
                             f"{r['pub']} · {r['assignee'][:40] or 'Unknown owner'} · {r['tech_label'] or r['tech_class']}")
            ready = orchestrator.report_path(r["pub"]).exists()
            st.markdown(f"{common.status_badge(r['status'])} {common.badge(str(r['end_year'] or '?'), 'gray')}"
                        + (f" {common.badge(':material/description: report ready', 'violet')}" if ready else ""))
            st.caption(f"{r['verdict']} · {r['confidence']} confidence · {r['fwd_after_end_unrelated']} citations after "
                       f"it died · {r['fwd_recent']} since {config.RECENT_SINCE}")
            if st.button("Open patent card", key=f"open_{r['pub']}", use_container_width=True, icon=":material/arrow_forward:"):
                common.open_patent(r["pub"])
    if len(rows) > 60:
        st.caption(f"Showing the top 60 of {len(rows)}. Narrow the filters to see more.")
