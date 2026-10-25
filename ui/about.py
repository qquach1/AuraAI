"""How it works: agent flow, score formula, guardrails, data sources (brief question 4)."""

import pandas as pd
import streamlit as st

from graveyard import config, scoring

from . import common

FLOW = """
digraph G {
  rankdir=TB; bgcolor="transparent"; nodesep=0.35; ranksep=0.45;
  node [shape=box, style="rounded,filled", fillcolor="#eef3fd", color="#5b8def", fontname="Helvetica", fontsize=12, margin="0.15,0.08"];
  edge [color="#8a8a8a", fontname="Helvetica", fontsize=10, fontcolor="#8a8a8a"];
  founder [label="Founder\\nsearch + filters", fillcolor="#ffffff", color="#999999"];
  orch [label="Orchestrator\\nroutes work, keeps the trace", fillcolor="#fff6e0", color="#e0a800"];
  scout [label="1  Scout\\ncandidates by class\\nand keyword"];
  status [label="2  Status\\nexpired, lapsed for fees,\\nor in force"];
  blocker [label="3  Blocker\\nfamily, follow-on patents,\\nregulatory exclusivity"];
  store [label="Evidence store\\nevery finding is a record", shape=cylinder, fillcolor="#f3f3f3", color="#999999"];
  market [label="4  Market\\ncitations, companies,\\nrevival score + confidence"];
  report [label="5  Report\\nscore, evidence, blockers,\\nassumption to test"];
  verifier [label="Verifier\\ndrops unsupported claims,\\nrewrites legal wording", fillcolor="#fdeeee", color="#d9534f"];
  prior [label="6  Prior-art agent\\nseparate check (Q3)", fillcolor="#eefaf0", color="#3c9d5d"];
  out [label="Triage report\\n+ disclaimer", fillcolor="#ffffff", color="#999999"];
  {rank=same; founder; orch; scout; status; blocker}
  {rank=same; store}
  {rank=same; out; verifier; report; market; prior}
  founder -> orch -> scout -> status -> blocker;
  blocker -> market [label=" back through scoring"];
  market -> report -> verifier -> out [dir=back];
  scout -> store [style=dashed, arrowhead=none]; status -> store [style=dashed, arrowhead=none];
  blocker -> store [style=dashed, arrowhead=none]; store -> market [style=dashed, arrowhead=none];
  store -> report [style=dashed];
  orch -> prior [style=dotted];
}
"""

AGENTS = [
    ("Scout", "Finds candidates in the graveyard by technology class and keyword", "SQLite full-text search; Claude expands plain words into patent vocabulary", "Ranked candidates"),
    ("Status", "Decides expired at term, lapsed for unpaid fees, or still in force", "Maintenance-fee legal events (code only)", "Status, lapse date, fee window, owner size, revival risk"),
    ("Blocker", "Checks what could still block use", "Family status, forward citations, blocker checklist; Claude rates follow-on overlap", "Blockers with severity and evidence"),
    ("Market", "Gathers commercial evidence and scores revival", "Citation activity, citing companies; Claude interprets", "Revival score with confidence"),
    ("Report", "Writes the triage report and the one assumption to test", "Claude, constrained to cite evidence IDs; verifier pass", "The report"),
    ("Prior-art", "Finds what an examiner would cite against a description", "Claude plans queries and reranks; patent search before the priority date", "Top 10 earlier patents"),
]


def page():
    st.title("How it works")
    st.markdown("Six agents and one orchestrator. Agents never call each other: the orchestrator passes work along "
                "and every finding is written to a shared evidence store. Code computes every number; Claude reads "
                "the numbers and writes, and it can only make claims that point at an evidence record.")
    st.graphviz_chart(FLOW, use_container_width=True)
    st.dataframe(pd.DataFrame(AGENTS, columns=["Agent", "Job", "Tools and data", "Output"]), hide_index=True,
                 use_container_width=True)

    st.subheader("Revival score")
    st.markdown("A transparent weighted sum of six signals, each scaled 0 to 1 by code. The report shows every component.")
    st.dataframe(pd.DataFrame([{"Signal": scoring.LABELS[k], "Weight": w} for k, w in scoring.WEIGHTS.items()]),
                 hide_index=True)
    st.markdown("60 or more reads as *a dead patent with a future*, 40 to 59 as *worth a closer look*, under 40 as "
                "*probably deserved to die*. Confidence (high, medium, low) reflects how much evidence the score "
                "rests on: citation volume, a recorded lapse event, a known entity size.")

    st.subheader("Guardrails")
    st.markdown(
        f"- **Research, not legal advice.** Every report carries this notice: _{config.DISCLAIMER}_\n"
        f"- **Expired is not free to use.** Every report runs the Blocker agent: live family members, follow-on "
        "patents, regulatory exclusivity (FDA, EPA), standards and revival risk.\n"
        "- **Anything typed counts as disclosed.** Search and prior-art inputs go to outside services. "
        "We only test with public patents, never our own unprotected ideas.\n"
        "- **Claims need evidence.** The verifier removes report points that cite no evidence record, and "
        "rewrites wording such as 'free to use' or 'no infringement'."
    )
    st.subheader("Data")
    st.markdown(f"Public US patent records from Google Patents pages (bibliographic data, legal events from the "
                f"USPTO maintenance-fee file, citations with examiner flags, family status), retrieved through "
                f"Internet Archive snapshots and saved locally so the demo runs offline. Each record shows its "
                f"snapshot date. All dates are evaluated as of {config.AS_OF.isoformat()}.")
    common.mode_caption()
