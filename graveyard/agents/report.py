"""Report agent: writes the triage report and names the one assumption to test first.

The score, confidence and verdict come from code and cannot be changed here. Claude
writes the reasoning; a verifier step then drops any point that cites no known evidence
record and rewrites wording that reads like a legal opinion.
"""

import re

from .. import config, llm

SYSTEM = (
    "You write triage reports for early-stage founders deciding whether a lapsed or expired "
    "US patent is worth building on. This is research and triage, never a legal opinion.\n\n"
    "Rules:\n"
    "- Use only the evidence provided. Every point must cite the evidence IDs (E1, E2, ...) it "
    "rests on. A point with no evidence will be deleted.\n"
    "- Never say an invention is free to use, patentable, valid, infringing or non-infringing, "
    "and never give freedom-to-operate conclusions. Say 'appears', 'may', 'worth checking'.\n"
    "- The revival score, confidence and verdict are computed by code; explain them, do not "
    "change them.\n"
    "- Write for a smart founder with no patent background: short sentences, plain words.\n"
    "- The assumption to test must be the single riskiest belief a founder would have to hold "
    "for this to be a business, with a concrete test they can run in under two weeks for under "
    "$500 (customer interviews, a landing page, a teardown, a quote from a manufacturer)."
)

POINT = llm.obj({"point": llm.STR, "evidence": llm.arr(llm.STR)})
SCHEMA = llm.obj({
    "headline": llm.STR,
    "what_it_is": llm.STR,
    "why_it_died": llm.obj({"text": llm.STR, "evidence": llm.arr(llm.STR), "confidence": llm.CONF}),
    "case_for": llm.arr(POINT),
    "case_against": llm.arr(POINT),
    "blockers": llm.arr(llm.obj({"point": llm.STR, "severity": llm.CONF, "evidence": llm.arr(llm.STR)})),
    "assumption_to_test": llm.obj({
        "assumption": llm.STR, "why_riskiest": llm.STR, "how_to_test": llm.STR, "evidence": llm.arr(llm.STR),
    }),
    "attorney_questions": llm.arr(llm.STR),
})

# Phrases that read like a legal conclusion, and the triage wording that replaces them.
REWRITES = [
    (r"\bfree to use\b", "possibly usable without a license (verify)"),
    (r"\b(is|are) (now )?in the public domain\b", r"\1 likely in the public domain (verify)"),
    (r"\b(?:effectively|essentially|now) (?:in the )?public domain\b", "likely in the public domain (verify)"),
    (r"\b(?:no|zero) (?:risk of )?infringement(?: risk)?\b", "an unassessed infringement risk"),
    (r"\bdoes not infringe\b", "has not been checked for infringement"),
    (r"\bis patentable\b", "may be patentable (not assessed)"),
    (r"\b(?:you |we )(?:have|get) (?:clear |full )?freedom[- ]to[- ]operate\b",
     "freedom to operate has not been assessed"),
    (r"\byou can (?:legally|freely) (use|copy|make|sell)\b", r"you may be able to \1"),
    (r"\byou are free to\b", "you may be able to"),
    (r"\bclear to (build|use|sell)\b", r"worth investigating to \1"),
]


_NEGATED = re.compile(r"\b(not|n't|never|no longer|isn't|aren't|doesn't mean)\b[^.;:]{0,25}$", re.I)


def scrub(text: str) -> str:
    for pat, rep in REWRITES:
        def sub(m, rep=rep):
            # "expired is not the same as free to use" is the guardrail itself, not a claim
            if _NEGATED.search(m.string[max(0, m.start() - 40):m.start()]):
                return m.group(0)
            out = m.expand(rep)
            return out[:1].upper() + out[1:] if m.group(0)[:1].isupper() else out
        text = re.sub(pat, sub, text, flags=re.I)
    return text


def verify(report: dict, known_ids: set[str]) -> tuple[dict, list[str]]:
    """Drop points without valid evidence, scrub legal-opinion wording. Returns (report, log)."""
    log = []

    def keep(points, name):
        out = []
        for p in points:
            ev = [e for e in p.get("evidence", []) if e in known_ids]
            if not ev:
                log.append(f"Removed a {name} point with no valid evidence: {p.get('point', '')[:80]}")
                continue
            out.append({**p, "point": scrub(p["point"]), "evidence": ev})
        return out

    report["case_for"] = keep(report.get("case_for", []), "case-for")
    report["case_against"] = keep(report.get("case_against", []), "case-against")
    report["blockers"] = keep(report.get("blockers", []), "blocker")
    wd = report.get("why_it_died", {})
    wd["evidence"] = [e for e in wd.get("evidence", []) if e in known_ids]
    wd["text"] = scrub(wd.get("text", ""))
    a = report.get("assumption_to_test", {})
    a["evidence"] = [e for e in a.get("evidence", []) if e in known_ids]
    for k in ("headline", "what_it_is"):
        before = report.get(k, "")
        report[k] = scrub(before)
        if report[k] != before:
            log.append(f"Rewrote legal-opinion wording in {k}")
    for k in ("assumption", "why_riskiest", "how_to_test"):
        a[k] = scrub(a.get(k, ""))
    report["attorney_questions"] = [scrub(q) for q in report.get("attorney_questions", [])]
    return report, log


def _fallback(patent, status, blockers, market) -> dict:
    """Rule-based report when Claude is unavailable. Same shape as the LLM output."""
    f, m, sc = patent["facts"], patent["metrics"], market["score"]
    st_ev = status["evidence"]
    ev = market["named"]
    since = config.RECENT_SINCE
    if f["status"] == "lapsed_fees":
        cause = []
        if f["entity_size"] in ("small", "micro"):
            cause.append(f"the owner was a {f['entity_size']} entity, which often means a cash-constrained startup or individual")
        if f["fee_window"] == 4:
            cause.append("it was dropped at the first fee window, before its value could be tested in the market")
        elif f["fees_paid"]:
            paid = " and ".join(f"{y}th-year" for y in f["fees_paid"])
            cause.append(f"the owner paid the {paid} fee(s) first, so it was valued for years before being dropped")
        if m["live_family"]:
            cause.append("the owner kept related family members alive, which suggests a deliberate choice")
        why = "It lapsed for unpaid maintenance fees" + (": " + "; ".join(cause) + "." if cause else ".")
    elif f["status"] == "expired_term":
        why = "It was not abandoned: it reached the end of its full 20-year term."
    else:
        why = "The record does not show a clean lapse or expiry."
    case_for, case_against = [], []
    if ev["after"] and m["fwd_after_end_unrelated"] >= 5:
        case_for.append({"point": f"{m['fwd_after_end_unrelated']} unrelated filings cited it after it died: the field kept going.",
                         "evidence": [ev["after"]]})
    if m["fwd_recent"] >= 3:
        case_for.append({"point": f"{m['fwd_recent']} filings since {since} build on it.", "evidence": [ev["recent"]]})
    if ev["companies"]:
        case_for.append({"point": "Named companies are still filing on top of it.", "evidence": [ev["companies"]]})
    if m["fwd_recent"] == 0:
        case_against.append({"point": f"Nothing filed since {since} cites it, so the field may have moved on.",
                             "evidence": [ev["recent"]]})
    if m["fwd_total"] < 4:
        case_against.append({"point": "Very few later patents cite it, so there is little evidence anyone needed it.",
                             "evidence": [ev["total"]]})
    if f["status"] == "lapsed_fees" and ev["after"] and m["fwd_after_end_unrelated"] < 3 <= m["fwd_total"]:
        case_against.append({"point": "Interest stopped when the owner stopped: few others cited it after it lapsed.",
                             "evidence": [ev["after"]]})
    elif f["status"] == "expired_term" and m.get("fwd_alive_unrelated", 0) < 3 <= m["fwd_total"]:
        case_against.append({"point": "Few unrelated filings cited it near the end of its term, so interest may have faded.",
                             "evidence": [ev["recent"]]})
    bl = [{"point": f"{b['title']}: {b['detail']}", "severity": b["severity"], "evidence": b["evidence"]}
          for b in blockers["blockers"] if b["kind"] != "trade_secret"][:5]
    return {
        "headline": f"{sc['verdict']}: revival score {sc['score']}/100 with {sc['confidence']} confidence.",
        "what_it_is": patent["abstract"][:400] + ("..." if len(patent["abstract"]) > 400 else ""),
        "why_it_died": {"text": why, "evidence": st_ev[:2], "confidence": "medium"},
        "case_for": case_for,
        "case_against": case_against,
        "blockers": bl,
        "assumption_to_test": {
            "assumption": "Customers today would pay for a product built on this invention.",
            "why_riskiest": "Citations show technical interest, not demand. Nothing in the patent record proves anyone will buy.",
            "how_to_test": "Interview 10 target customers this week about the problem the patent solves and ask what they use "
                           "and pay today; count how many would pre-order.",
            "evidence": [ev["score"]],
        },
        "attorney_questions": [
            f"Is {patent['pub']} still lapsed, and has any petition to revive it been filed?",
            "Do any of the listed follow-on or family patents claim what our product would need?",
            "Are there regulatory exclusivities or standards obligations in this field we must clear?",
        ],
    }


def run(patent: dict, store, status: dict, blockers: dict, market: dict, nearby: dict | None,
        usage=None, use_llm: bool = True) -> dict:
    sc = market["score"]
    report, mode = None, "rules"
    if use_llm and config.llm_available():
        ev = "\n".join(f"{e.id} [{e.agent}, {e.confidence}]: {e.claim}" for e in store.items)
        comps = "\n".join(f"- {c['label']}: {c['points']}/{c['weight']}" for c in sc["components"].values())
        near = "\n".join(f"- {n['pub']}: {n['title']} (score {n['score']})" for n in (nearby or {}).get("items", []))
        f = patent["facts"]
        user = (
            f"Patent {patent['pub']}: {patent['title']}\nField: {patent['tech_label']} (CPC {patent['cpc_first']})\n"
            f"Owner: {patent['assignee']}\nPriority {f['priority_date']}, granted {f['grant_date']}, "
            f"status {f['status']}, ended {f['end_date']}\n\nAbstract: {patent['abstract']}\n\n"
            f"First claim: {patent['record'].get('claims', {}).get('first', '')[:2000]}\n\n"
            f"Computed revival score: {sc['score']}/100, confidence {sc['confidence']}, verdict '{sc['verdict']}'.\n"
            f"Score breakdown:\n{comps}\n\nMarket read from the Market agent: {market['read'].get('market_read', '')}\n\n"
            f"Other dead patents nearby in the sample:\n{near or '- none'}\n\nEvidence records:\n{ev}\n\n"
            "Write the report. Keep `headline` to one sentence that states the verdict. `what_it_is`: two plain sentences. "
            "Give 2-4 points each for case_for and case_against, and the 3-5 most important blockers. "
            "3 attorney_questions."
        )
        report = llm.structured("report", SYSTEM, user, SCHEMA, usage, effort="medium", max_tokens=16000)
        if report:
            mode = "claude"
    if not report:
        report = _fallback(patent, status, blockers, market)

    report, log = verify(report, set(store.by_id()))
    report.update(score=sc["score"], confidence=sc["confidence"], verdict=sc["verdict"],
                  disclaimer=config.DISCLAIMER, mode=mode, verifier_log=log)
    report["summary"] = f"Report written ({mode}); verifier removed {sum('Removed' in l for l in log)} unsupported points"
    return report
