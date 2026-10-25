"""Market agent: commercial evidence and the revival score (brief question 2).

Code computes the signals (citation activity after the patent died, recent filings that
build on it, the companies doing that filing) and the score. Claude, when available,
reads those numbers and says what kind of market they point to, citing evidence IDs.
"""

from .. import config, gp, llm, scoring
from .report import scrub

SYSTEM = (
    "You are a market-research analyst helping an early-stage founder triage a lapsed or "
    "expired patent. You get computed citation evidence, each item with an ID. Interpret what "
    "the evidence says about commercial interest in the field today. Every signal you write "
    "must cite at least one evidence ID it rests on. Rate confidence honestly: citation counts "
    "show technical interest, not proof of revenue. Do not invent companies, products, sales "
    "figures or market sizes; name only companies that appear in the evidence. This is research, "
    "not a legal opinion: never say anything is in the public domain, free to use, infringing, or "
    "clear for freedom to operate."
)

SCHEMA = llm.obj({
    "signals": llm.arr(llm.obj({
        "signal": llm.STR,
        "evidence": llm.arr(llm.STR),
        "confidence": llm.CONF,
    })),
    "who_is_active": llm.STR,
    "market_read": llm.STR,
})


WEB_SYSTEM = (
    "You research current commercial activity around an expired or lapsed patent for a founder. "
    "Search the web for products on sale today, companies working on the same problem, and market "
    "or adoption signals. Report only what a page you found actually says, with its URL. Prefer "
    "company product pages, filings and reputable press over blogs. Never claim anyone infringes "
    "or that anything is free to use."
)


def _web_evidence(patent: dict, store, usage) -> list[dict]:
    """Claude web search for products, companies and market signals; each finding becomes evidence."""
    text = llm.web_research(
        "market_web", WEB_SYSTEM,
        f"Patent {patent['pub']}: {patent['title']}\nField: {patent['tech_label']}\nAbstract: {patent['abstract'][:1200]}\n\n"
        "Find up to 4 concrete, current signals. Finish with a JSON object in a ```json block: "
        '{"findings": [{"kind": "product" | "company" | "market", "finding": "one sentence", '
        '"url": "https://...", "confidence": "high" | "medium" | "low"}]}',
        usage, max_uses=4)
    data = llm.extract_json(text) or {}
    out = []
    for f in data.get("findings", [])[:4]:
        url = f.get("url", "")
        if not url.startswith("http") or not f.get("finding"):
            continue
        conf = f.get("confidence") if f.get("confidence") in ("medium", "low") else "medium"  # web claims cap at medium
        f["finding"] = scrub(f["finding"])
        eid = store.add("market", f"{f.get('kind', 'market').capitalize()}: {f['finding']}", url,
                        "Claude web search (page found and summarized, not independently verified)", conf)
        out.append({**f, "evidence": eid, "confidence": conf})
    return out


def run(patent: dict, store, regulatory_burden: str, usage=None, use_llm: bool = True) -> dict:
    f, m = patent["facts"], patent["metrics"]
    url = gp.patent_url(patent["pub"])
    ids = []
    died = "lapsed" if f["status"] == "lapsed_fees" else "expired"

    ids.append(store.add("market", f"Cited by {m['fwd_total']} later patents and applications in total.",
                         url + "#citedBy", "Count of forward citations", "high", n=m["fwd_total"]))
    id_after = None
    if f["end_date"]:
        id_after = store.add(
            "market", f"{m['fwd_after_end_unrelated']} later filings by unrelated owners cite it with priority dates after it "
            f"{died} ({f['end_date']}).", url + "#citedBy",
            "Forward citations with priority after the end date, excluding the original owner", "high",
            n=m["fwd_after_end_unrelated"])
        ids.append(id_after)
    if f["status"] == "expired_term" and m.get("fwd_alive_unrelated"):
        ids.append(store.add(
            "market", f"{m['fwd_alive_unrelated']} filings by unrelated owners cited it in its last five years of term "
            "or after it expired.", url + "#citedBy",
            "Forward citations with priority after (term end minus 5 years), excluding the original owner", "high"))
    since = config.RECENT_SINCE
    id_recent = store.add("market", f"{m['fwd_recent']} citing filings have priority dates from {since} on.",
                          url + "#citedBy", f"Forward citations with priority in the last {config.RECENT_YEARS} years "
                          "(recent filings publish with an 18-month lag)", "high", n=m["fwd_recent"])
    ids.append(id_recent)
    id_companies = None
    if m["recent_companies"]:
        names = ", ".join(f"{n} ({k})" for n, k in m["recent_companies"][:6])
        id_companies = store.add("market", f"Companies filing on top of it since {since}: {names}.", url + "#citedBy",
                                 f"Assignees of citing filings with priority from {since} on", "medium",
                                 companies=m["recent_companies"][:6])
        ids.append(id_companies)
    if m["fwd_examiner"]:
        ids.append(store.add("market", f"Examiners cited it against {m['fwd_examiner']} later applications.",
                             url + "#citedBy", "Forward citations marked as examiner-cited", "high"))
    if m["shortest_claim_words"]:
        ids.append(store.add("market", f"Its shortest independent claim is {m['shortest_claim_words']} words "
                             f"across {m['claims_count']} claims.", url + "#claims", "Word count of independent claims", "high"))
    if m["family_countries"]:
        ids.append(store.add("market", f"The family was filed in {m['family_countries']} jurisdiction(s).",
                             url + "#family", "Countries in the patent family", "medium"))

    sc = scoring.score(f, m, regulatory_burden)
    top = sorted(sc["components"].values(), key=lambda c: -c["points"])
    id_score = store.add("market", f"Revival score {sc['score']}/100 ({sc['confidence']} confidence); strongest signals: "
                         f"{top[0]['label']} and {top[1]['label']}.", "Computed by Graveyard Shift",
                         "Weighted sum of six named signals; see the score breakdown", sc["confidence"])
    ids.append(id_score)
    named = {"total": ids[0], "after": id_after, "recent": id_recent, "companies": id_companies, "score": id_score}

    web = []
    if use_llm and config.llm_available() and config.WEB_EVIDENCE:
        web = _web_evidence(patent, store, usage)

    read = None
    if use_llm and config.llm_available():
        ev = "\n".join(f"{e.id}: {e.claim}" for e in store.for_agent("market") + store.for_agent("status"))
        read = llm.structured(
            "market", SYSTEM,
            f"Patent {patent['pub']}: {patent['title']}\nField: {patent['tech_label']}\n"
            f"Abstract: {patent['abstract'][:1500]}\n\nEvidence:\n{ev}\n\n"
            "Return 2 to 4 signals, a sentence on who is active in this space now, and a two-sentence market read.",
            SCHEMA, usage, effort="low", max_tokens=4000,
        )
        if read:
            known = store.by_id()
            read["signals"] = [{**s, "signal": scrub(s["signal"])} for s in read["signals"]
                               if any(e in known for e in s["evidence"])]
            read["market_read"] = scrub(read["market_read"])
            read["who_is_active"] = scrub(read["who_is_active"])

    if not read:
        read = {"signals": [], "who_is_active": "", "market_read": ""}
        if id_after and m["fwd_after_end_unrelated"] >= 5:
            read["signals"].append({"signal": "Other companies kept building on this idea after the owner let it go.",
                                    "evidence": [id_after], "confidence": "medium"})
        if m["fwd_recent"] >= 3:
            read["signals"].append({"signal": "The field is still active: recent filings cite it.",
                                    "evidence": [id_recent], "confidence": "medium"})
        elif m["fwd_recent"] == 0:
            read["signals"].append({"signal": "No recent filings cite it, so the field may have moved on.",
                                    "evidence": [id_recent], "confidence": "medium"})
        if m["recent_companies"]:
            read["who_is_active"] = "Recent citing filers include " + ", ".join(n for n, _ in m["recent_companies"][:3]) + "."

    return {
        "score": sc,
        "metrics": m,
        "read": read,
        "web": web,
        "evidence": ids,
        "named": named,
        "summary": f"Score {sc['score']}/100, {sc['confidence']} confidence: {sc['verdict']}",
    }
