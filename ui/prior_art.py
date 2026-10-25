"""Prior-art check: paste a public patent's description, get the earlier patents an
examiner would likely cite."""

import json
from datetime import date

import pandas as pd
import streamlit as st

from graveyard import config, gp, llm
from graveyard.agents import prior_art

from . import common


def _examples() -> list[dict]:
    p = config.BENCHMARK_DIR / "targets.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else []


def page():
    st.title("Prior-art check")
    st.markdown("Give the agent a patent-style description. It searches the way an examiner does and returns "
                "the earlier patents most likely to be cited against it.")
    common.disclosure_notice()

    examples = _examples()
    ex = None
    if examples:
        names = ["(type my own)"] + [f"{t['pub']} · {t['title'][:70]}" for t in examples]
        pick = st.selectbox("Or load a public benchmark patent (its citations are hidden from the agent)", names)
        if pick != names[0]:
            ex = examples[names.index(pick) - 1]

    text = st.text_area("Description", value=(ex["input"] if ex else ""), height=220,
                        placeholder="Title, what it does, how it works, and 3-5 claim-like sentences.")
    default_cut = date.fromisoformat(ex["priority_date"]) if ex else config.AS_OF
    cutoff = st.date_input("Only search documents with a priority date before", value=default_cut)
    ok = st.checkbox("This text is from a public patent or an idea that is already protected.", value=bool(ex))

    cache_key = f"pa_{hash((text, cutoff.isoformat()))}"
    live = common.live_allowed()
    label = "Find prior art" + ("" if live else " (keyword search only)")
    if st.button(label, type="primary", disabled=not (ok and text.strip()), icon=":material/travel_explore:"):
        exclude = set(ex["exclude"]) if ex else set()
        usage = llm.Usage()
        with st.status("Searching like an examiner...", expanded=True) as box:
            res = prior_art.run(text, cutoff.strftime("%Y%m%d"), exclude, backend=prior_art.default_backend(common.con()),
                                usage=usage, use_llm=live, on_step=box.write)
            box.update(label=f"Ranked {res['pool_size']} candidates", state="complete", expanded=False)
        if live:
            common.count_live_run()
        res["cost"] = usage.total_cost
        st.session_state[cache_key] = res
    common.mode_caption()

    res = st.session_state.get(cache_key)
    if not res and ex and ex.get("saved_run") and text == ex["input"]:
        res = ex["saved_run"]
        st.caption(f"Showing the saved benchmark run from {ex.get('run_at', 'the benchmark')}. Press the button to run it live.")
    if not res:
        return
    truth = {prior_art.norm_pub(p) for p in ex["examiner_refs"]} if ex else set()
    if res["plan"]["elements"]:
        st.markdown("**Claim elements the agent searched for**")
        for e in res["plan"]["elements"]:
            st.markdown(f"- {e}")
    rows = []
    for i, r in enumerate(res["results"], 1):
        rows.append({
            "rank": i,
            "patent": gp.patent_url(r["pub"]),
            "title": r["title"],
            "priority": r.get("priority_date"),
            "owner": r.get("assignee"),
            "why": r.get("why") or r.get("snippet", "")[:160],
            **({"examiner cited": "yes" if prior_art.norm_pub(r["pub"]) in truth else ""} if ex else {}),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                 column_config={"patent": st.column_config.LinkColumn(display_text=r"patent/(.*?)/en")})
    if ex:
        hits = sum(1 for r in rows if r.get("examiner cited"))
        st.success(f"{hits} of the top {len(rows)} were cited by the examiner (out of {len(truth)} examiner-cited US references).")
    cost = f"; model cost ${res['cost']:.3f}" if "cost" in res else ""
    st.caption(f"Searched {res['backend']}; ranking: {res['rank_mode']}{cost}.")
    with st.expander("Search log"):
        for q in res["plan"]["queries"]:
            st.markdown(f"- `{q['query']}` ({q['targets']})")
        for line in res["log"]:
            st.caption(line)
