"""Proof: the prior-art benchmark (brief question 3)."""

import json
import re

import altair as alt
import pandas as pd
import streamlit as st

from graveyard import config, gp


def page():
    st.title("Proof: does the agent find what an examiner found?")
    p = config.BENCHMARK_DIR / "results.json"
    if not p.exists():
        st.info("No benchmark results yet. Run `python scripts/run_benchmark.py`.")
        return
    res = json.loads(p.read_text("utf-8"))
    s = res["summary"]
    n_docs = re.search(r"([\d,]+) (?:US )?documents", res["backend"])
    st.markdown(
        f"We took **{s['n_targets']} recently granted public US patents**, hid their citation lists, and gave the agent "
        f"only each one's title, abstract and first claim. It searched a pool of "
        f"{n_docs.group(1) if n_docs else 'about 36,000'} US documents, limited to those filed before the patent's "
        f"priority date. Then we counted how many of the examiner's own citations it put in its top 10."
    )
    c = st.columns(4)
    c[0].metric("Examiner refs found", f"{s['agent_hits']} of {s['truth_total']}",
                help="Examiner-cited references in the agent's top 10, summed over all targets")
    c[1].metric("Agent recall@10", f"{s['agent_recall']:.0%}",
                delta=f"{(s['agent_recall'] - s['baseline_recall']) * 100:+.0f} pts vs keyword")
    c[2].metric("Keyword recall@10", f"{s['baseline_recall']:.0%}", help="One keyword search over the same pool")
    c[3].metric("Targets with a hit", f"{s['agent_success']} of {s['n_targets']}",
                help=f"Keyword search: {s['baseline_success']} of {s['n_targets']}")

    df = pd.DataFrame(res["targets"])
    long = pd.concat([
        pd.DataFrame({"patent": df["pub"], "system": "Agent", "found": df["agent_hits"]}),
        pd.DataFrame({"patent": df["pub"], "system": "Keyword search", "found": df["baseline_hits"]}),
    ])
    chart = alt.Chart(long).mark_bar().encode(
        y=alt.Y("patent:N", title=None, sort=list(df["pub"])),
        x=alt.X("found:Q", title="Examiner-cited references found in the top 10"),
        color=alt.Color("system:N", scale=alt.Scale(range=["#5b8def", "#c5c5c5"]), legend=alt.Legend(orient="bottom")),
        yOffset="system:N",
        tooltip=["patent", "system", "found"],
    ).properties(height=40 * len(df) + 40)
    st.altair_chart(chart, use_container_width=True)

    if s["in_corpus_total"] < s["truth_total"]:
        st.caption(f"Ceiling: only {s['in_corpus_total']} of the {s['truth_total']} examiner references are in the search "
                   f"pool at all, so the best possible recall is {s['in_corpus_total'] / s['truth_total']:.0%}.")
    st.caption("Recall@10 is capped below 100% for targets with more than 10 examiner references.")
    st.dataframe(pd.DataFrame([{
        "patent": gp.patent_url(t["pub"]), "title": t["title"], "priority": t["priority_date"],
        "examiner refs (US)": t["truth_n"], "reachable in corpus": t["in_corpus"],
        "agent hits@10": t["agent_hits"], "keyword hits@10": t["baseline_hits"],
    } for t in res["targets"]]), hide_index=True, use_container_width=True,
        column_config={"patent": st.column_config.LinkColumn(display_text=r"patent/(.*?)/en")})

    st.markdown("#### How the test was run")
    for line in res["method"]:
        st.markdown(f"- {line}")
    st.caption(f"Run {res['run_at']} · search backend: {res['backend']} · model {res.get('model') or 'none'} · "
               f"model cost ${res.get('cost_usd', 0):.2f}")
