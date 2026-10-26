"""Simulation Lab: the same agents, pointed at a founder's idea instead of a patent.

Scout finds dead patents in the graveyard that solve part of the idea, the Prior-art agent
maps the closest earlier patents (flagging ones that may still be in force), the Market
agent searches the web for size, growth and players, and the Report agent writes strategic
pathways and the one assumption to test. Every pathway must cite an evidence record.
"""

import json
from datetime import datetime, timezone

from .. import config, db, gp, llm
from . import prior_art, scout
from .base import EvidenceStore
from .report import scrub

EXAMPLE_PATH = config.DATA_DIR / "simulations" / "example.json"
EXAMPLE_IDEA = ("A wearable device for continuous glucose monitoring using non-invasive optical sensors, "
                "sold to people with type 2 diabetes who dislike finger-prick tests.")

MARKET_SYSTEM = (
    "You size up the market for a technology idea for an early-stage founder. Search the web for "
    "market size and growth estimates, the main companies and products, and adoption signals. Report "
    "only what a page you found says, with its URL. Give the source's own numbers and year; never "
    "invent or average figures. Never say anything is free to use or infringing."
)

BRIEF_SYSTEM = (
    "You are a startup strategist doing patent-aware triage for a founder. This is research, not a "
    "legal opinion: never say anything is free to use, patentable, infringing or clear to operate. "
    "Use only the evidence records provided and cite their IDs. Write in short plain sentences."
)
PATHWAY = llm.obj({"name": llm.STR, "detail": llm.STR, "evidence": llm.arr(llm.STR)})
BRIEF_SCHEMA = llm.obj({
    "summary": llm.STR,
    "white_space": llm.STR,
    "pathways": llm.arr(PATHWAY),
    "assumption_to_test": llm.obj({"assumption": llm.STR, "how_to_test": llm.STR}),
    "attorney_questions": llm.arr(llm.STR),
})


def _market(idea: str, store: EvidenceStore, usage) -> list[dict]:
    text = llm.web_research(
        "simulate_market", MARKET_SYSTEM,
        f"Idea: {idea[:1500]}\n\nFind up to 5 signals. Finish with a JSON object in a ```json block: "
        '{"signals": [{"kind": "size" | "growth" | "player" | "product" | "adoption", "finding": "one sentence '
        'with the source\'s own numbers and year", "url": "https://...", "confidence": "medium" | "low"}]}',
        usage, max_uses=8)
    out = []
    for s in (llm.extract_json(text) or {}).get("signals", [])[:5]:
        if not str(s.get("url", "")).startswith("http") or not s.get("finding"):
            continue
        conf = s.get("confidence") if s.get("confidence") in ("medium", "low") else "medium"
        finding = scrub(s["finding"])
        eid = store.add("market", f"{s.get('kind', 'market').capitalize()}: {finding}", s["url"],
                        "Claude web search (page found and summarized, not independently verified)", conf)
        out.append({**s, "finding": finding, "confidence": conf, "evidence": eid})
    return out


def run(con, idea: str, usage=None, use_llm: bool = True, on_step=None) -> dict:
    usage = usage or llm.Usage()
    store = EvidenceStore()
    use_llm = use_llm and config.llm_available()

    def step(msg):
        if on_step:
            on_step(msg)

    # 1. Scout: dead patents in the graveyard that solve part of the idea
    step("**Scout** is looking for dead patents that already solve part of this")
    expansion = scout.expand(idea[:600], usage) if use_llm else {"terms": []}
    rows = db.search(con, " ".join([idea] + expansion["terms"]), statuses=["lapsed_fees", "expired_term"], limit=5)
    graveyard = []
    for r in rows:
        eid = store.add("scout", f"{r['pub']} ({r['title'][:90]}) is {'lapsed' if r['status'] == 'lapsed_fees' else 'expired'} "
                        f"(ended {r['end_year']}) and scores {r['score']}/100 for revival.",
                        gp.patent_url(r["pub"]), "Full-text match in the graveyard sample", "medium")
        graveyard.append({"pub": r["pub"], "title": r["title"], "status": r["status"], "end_year": r["end_year"],
                          "score": r["score"], "evidence": eid})

    # 2. Prior-art agent: the closest earlier patents, live or dead
    step("**Prior-art agent** is mapping the closest earlier patents")
    pa = prior_art.run(idea, config.AS_OF.strftime("%Y%m%d"), set(), backend=prior_art.LocalBackend(con),
                       k=8, usage=usage, use_llm=use_llm)
    dead = {r["pub"] for r in con.execute("SELECT pub FROM patents")}
    landscape = []
    for r in pa["results"]:
        pri = r.get("priority_date") or ""
        maybe_live = r["pub"] not in dead and pri >= f"{config.AS_OF.year - 20}{config.AS_OF.isoformat()[4:]}"
        label = "in the graveyard" if r["pub"] in dead else ("may still be in force" if maybe_live else "past 20-year term")
        eid = store.add("prior_art", f"{r['pub']} ({r['title'][:90]}), priority {pri or '?'}: {label}.",
                        gp.patent_url(r["pub"]), "Prior-art search over the local corpus"
                        + ("; Claude reranked" if pa["rank_mode"] == "claude rerank" else ""), "medium")
        landscape.append({"pub": r["pub"], "title": r["title"], "priority_date": pri, "assignee": r.get("assignee"),
                          "standing": label, "why": r.get("why"), "evidence": eid})

    # 3. Market agent: size, growth and players from the web
    market = []
    if use_llm and config.WEB_EVIDENCE:
        step("**Market agent** is searching the web for size, growth and key players")
        market = _market(idea, store, usage)

    # 4. Report agent: strategic pathways and the one assumption to test
    step("**Report agent** is writing strategic pathways and the assumption to test")
    brief = None
    if use_llm:
        ev = "\n".join(f"{e.id} [{e.agent}]: {e.claim}" for e in store.items)
        brief = llm.structured(
            "simulate", BRIEF_SYSTEM,
            f"Founder's idea: {idea[:2000]}\n\nEvidence:\n{ev}\n\n"
            "Write: `summary` (two sentences on the opportunity and the main patent risk); `white_space` (one "
            "sentence on what the landscape does not seem to cover, hedged); 3 `pathways` such as building on "
            "expired patents, designing around live ones, licensing or partnering, each citing evidence; the one "
            "riskiest assumption with a test that costs under $500 and takes under two weeks; 3 attorney_questions.",
            BRIEF_SCHEMA, usage, effort="medium", max_tokens=8000)
    if brief:
        known = set(store.by_id())
        brief["pathways"] = [{**p, "detail": scrub(p["detail"]), "evidence": [e for e in p["evidence"] if e in known]}
                             for p in brief["pathways"] if any(e in known for e in p["evidence"])]
        for k in ("summary", "white_space"):
            brief[k] = scrub(brief[k])
        brief["assumption_to_test"] = {k: scrub(v) for k, v in brief["assumption_to_test"].items()}
        mode = "claude"
    else:
        live = [x for x in landscape if x["standing"] == "may still be in force"]
        brief = {
            "summary": "Rule-based summary: the patents below are the closest matches in our data. Read the expired "
                       "ones as free background and check the possibly live ones before building.",
            "white_space": "",
            "pathways": ([{"name": "Build on expired patents", "detail": "Start from what the dead patents below already "
                           "disclose.", "evidence": [g["evidence"] for g in graveyard[:3]]}] if graveyard else [])
                        + ([{"name": "Check possibly live patents", "detail": "These earlier patents may still be in "
                             "force; review their claims before designing.", "evidence": [x["evidence"] for x in live[:3]]}]
                           if live else []),
            "assumption_to_test": {"assumption": "Target customers have this problem badly enough to pay for a fix.",
                                   "how_to_test": "Interview 10 target customers this week about how they solve it today "
                                                  "and what they pay."},
            "attorney_questions": ["Which of the possibly live patents listed here should we read claim by claim?"],
        }
        mode = "rules"

    return {
        "idea": idea,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "model": config.MODEL if mode == "claude" else None,
        "graveyard": graveyard,
        "landscape": landscape,
        "market": market,
        "brief": brief,
        "evidence": store.to_list(),
        "disclaimer": config.DISCLAIMER,
        "cost_usd": usage.total_cost,
    }


def load_example() -> dict | None:
    return json.loads(EXAMPLE_PATH.read_text("utf-8")) if EXAMPLE_PATH.exists() else None


def save_example(out: dict):
    EXAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXAMPLE_PATH.write_text(json.dumps(out, indent=1, default=str), "utf-8")
