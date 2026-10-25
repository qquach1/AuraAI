"""Blocker agent: what could still stop a founder after the patent died.

Checks, in order: live family members, follow-on patents by the same owner, later
patents examiners tied to this one, regulatory exclusivity and approvals for the field
(from the blocker checklist), and revival risk. Claude, when available, reads the
candidate follow-on titles against the patent and rates how likely each one is to cover
what a product built on this patent would need.
"""

from datetime import timedelta

from .. import checklist, config, derive, gp, llm

YEAR = 365.25

SYSTEM = (
    "You are a patent research assistant doing triage, not giving legal opinions. Given a "
    "lapsed or expired patent and a list of later patents that cite it, judge for each later "
    "patent how likely it is to claim an improvement that a product built on the original "
    "would need. Use only the titles, owners and dates provided. Never say anything is free "
    "to use, infringing or non-infringing."
)

SCHEMA = llm.obj({
    "ratings": llm.arr(llm.obj({
        "pub": llm.STR,
        "overlap": {"type": "string", "enum": ["high", "medium", "low"]},
        "reason": llm.STR,
    })),
})


def _maybe_in_force(f: dict) -> bool:
    pri = derive.d(f.get("priority_date")) or derive.d(f.get("publication_date"))
    return bool(pri) and pri + timedelta(days=round(20 * YEAR)) > config.AS_OF


def _cached_status(pub: str) -> str | None:
    if not gp.is_cached(pub):
        return None
    try:
        return gp.get_patent(pub).get("legal_status") or None
    except Exception:
        return None


def run(patent: dict, store, usage=None, use_llm: bool = True) -> dict:
    rec, f = patent["record"], patent["facts"]
    url = gp.patent_url(patent["pub"])
    blockers = []

    # 1. Live family members (continuations, divisionals, foreign counterparts)
    live = [a for a in rec.get("family_apps", [])
            if a.get("pub") and a["pub"] != patent["pub"] and a.get("status", "").lower().startswith("active")]
    if live:
        names = ", ".join(a["pub"] for a in live[:5])
        eid = store.add("blocker", f"{len(live)} family member(s) are still active: {names}.",
                        url + "#family", "Family applications with an Active status", "high",
                        pubs=[a["pub"] for a in live])
        blockers.append({"kind": "family", "severity": "high", "title": "Live family members",
                         "detail": f"{len(live)} related application(s) still active ({names}). "
                                   "A live continuation can claim the same invention.",
                         "evidence": [eid], "items": live[:5]})

    # 2. Follow-on patents by the same owner that may still be in force
    owners = {derive.norm_assignee(a) for a in rec.get("assignee_original", []) + rec.get("assignee_current", [])}
    owners.discard("")
    fwd = rec.get("forward", []) + rec.get("forward_family", [])
    seen, same_owner, examiner_linked = set(), [], []
    for c in fwd:
        if c["pub"] in seen or not _maybe_in_force(c):
            continue
        seen.add(c["pub"])
        known = _cached_status(c["pub"])
        if known and not known.lower().startswith("active"):
            continue  # we know it is dead too
        c = {**c, "known_status": known}
        if derive.norm_assignee(c["assignee"]) in owners:
            same_owner.append(c)
        elif c["examiner"]:
            examiner_linked.append(c)
    same_owner.sort(key=lambda c: c.get("priority_date") or "", reverse=True)
    examiner_linked.sort(key=lambda c: c.get("priority_date") or "", reverse=True)

    ratings = {}
    candidates = same_owner[:8] + examiner_linked[:8]
    if candidates and use_llm and config.llm_available():
        lines = "\n".join(f"- {c['pub']} | {c['priority_date']} | {c['assignee']} | {c['title']}" for c in candidates)
        out = llm.structured(
            "blocker", SYSTEM,
            f"Original patent {patent['pub']}: {patent['title']}\nAbstract: {patent['abstract'][:1500]}\n"
            f"First claim: {rec.get('claims', {}).get('first', '')[:1200]}\n\nLater patents that cite it "
            f"(pub | priority date | owner | title):\n{lines}\n\nRate every listed patent.",
            SCHEMA, usage, effort="low", max_tokens=4000,
        )
        if out:
            ratings = {r["pub"]: r for r in out["ratings"]}

    def describe(cs):
        out = []
        for c in cs:
            r = ratings.get(c["pub"], {})
            out.append({**c, "overlap": r.get("overlap"), "reason": r.get("reason")})
        order = {"high": 0, "medium": 1, "low": 2, None: 1}
        return sorted(out, key=lambda c: order[c["overlap"]])

    if same_owner:
        items = describe(same_owner)[:5]
        method = "Forward citations from the same owner, priority within the last 20 years"
        if ratings:
            method += "; overlap rated by Claude from titles"
        eid = store.add("blocker", f"The owner filed {len(same_owner)} later patent(s) citing this one that may still be in force, "
                        f"e.g. {items[0]['pub']} ({items[0]['title'][:80]}).",
                        url + "#citedBy", method, "medium", pubs=[c["pub"] for c in items])
        sev = "high" if any(c["overlap"] == "high" for c in items) or not ratings else "medium"
        blockers.append({"kind": "follow_on", "severity": sev, "title": "Owner's follow-on patents",
                         "detail": "The original owner kept filing in this area. These later patents may claim the "
                                   "improvements a product needs; their status is unverified unless shown.",
                         "evidence": [eid], "items": items})
    if examiner_linked:
        items = describe(examiner_linked)[:5]
        eid = store.add("blocker", f"{len(examiner_linked)} later patent(s) by other owners were cited against this one by examiners "
                        "and may still be in force.", url + "#citedBy",
                        "Examiner-cited forward citations, priority within the last 20 years", "medium",
                        pubs=[c["pub"] for c in items])
        sev = "medium" if any(c["overlap"] == "high" for c in items) else "low"
        blockers.append({"kind": "nearby_live", "severity": sev, "title": "Live patents examiners linked to this one",
                         "detail": "Examiners judged these later patents close enough to cite this one. Check whether "
                                   "their claims cover your product.", "evidence": [eid], "items": items})

    # 3. Field-specific checklist items (regulatory exclusivity, approvals, standards)
    cpc = [c["code"] for c in rec.get("cpc", [])]
    for rule in checklist.matching(cpc):
        if "all" in rule["applies_to"]:
            continue
        eid = store.add("blocker", f"{rule['title']}: {rule['check']}", rule["where_to_look"],
                        f"Blocker checklist rule '{rule['id']}' matched CPC {', '.join(cpc[:3])}", "medium")
        blockers.append({"kind": "regulatory", "severity": rule["burden"], "title": rule["title"],
                         "detail": rule["check"], "where": rule["where_to_look"], "evidence": [eid]})

    # 4. Revival risk
    if f["revival_risk"]:
        eid = store.add("blocker", f"Lapsed {f['months_since_end']:.0f} months ago; the owner can still petition to revive it.",
                        url + "#legalEvents", "Months since lapse under 24", "high")
        blockers.append({"kind": "revival", "severity": "high", "title": "Revival risk",
                         "detail": "A late-fee petition could put the patent back in force.", "evidence": [eid]})
    elif f["status"] == "lapsed_fees":
        eid = store.add("blocker", "No reinstatement event is on record since the lapse.", url + "#legalEvents",
                        "Searched legal events for reinstatement codes", "high")
        ago = f"Lapsed {f['months_since_end']:.0f} months ago" if f["months_since_end"] else "Lapsed"
        blockers.append({"kind": "revival", "severity": "low", "title": "Revival risk",
                         "detail": f"{ago} with no reinstatement on record; revival this late requires a "
                                   "petition showing the delay was unintentional.",
                         "evidence": [eid]})

    # Always-on reminders from the checklist
    for rule in checklist.matching(cpc):
        if rule["id"] == "trade_secret":
            eid = store.add("blocker", rule["check"], rule["where_to_look"], "Blocker checklist", "low")
            blockers.append({"kind": "trade_secret", "severity": "low", "title": rule["title"],
                             "detail": rule["check"], "evidence": [eid]})

    order = {"high": 0, "medium": 1, "low": 2}
    blockers.sort(key=lambda b: order[b["severity"]])
    n_high = sum(b["severity"] == "high" for b in blockers)
    return {
        "blockers": blockers,
        "regulatory_burden": checklist.burden(cpc),
        "llm_rated": bool(ratings),
        "summary": f"{len(blockers)} possible blockers, {n_high} high severity",
    }
