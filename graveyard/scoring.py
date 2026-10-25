"""Revival score: a transparent weighted sum of named signals (brief question 1).

Each signal is scaled to 0..1 by code, then weighted. The report shows every component,
so a founder can see why a patent scored the way it did and disagree with a weight.
"""

import math

WEIGHTS = {
    "field_alive": 30,      # others kept citing it after it died
    "momentum": 20,         # citations from recent filings (config.RECENT_YEARS)
    "non_merit_death": 15,  # signs it died for money, not merit
    "breadth": 15,          # short independent claim, filed in several countries
    "examiner_relevance": 10,  # examiners cited it against later applications
    "clear_path": 10,       # no live family members and a light regulatory path
}

LABELS = {
    "field_alive": "Field still alive",
    "momentum": "Recent momentum",
    "non_merit_death": "Died for money, not merit",
    "breadth": "Breadth at grant",
    "examiner_relevance": "Examiner relevance",
    "clear_path": "Clear path",
}


def _log_scale(n: int, cap: int) -> float:
    return min(1.0, math.log1p(max(0, n)) / math.log1p(cap))


def components(facts: dict, m: dict, regulatory_burden: str = "low") -> dict:
    status = facts["status"]

    field_alive = _log_scale(m.get("fwd_alive_unrelated", m["fwd_after_end_unrelated"]), 25)
    momentum = _log_scale(m["fwd_recent"], 12)

    if status == "lapsed_fees":
        nm = 0.35
        if facts.get("entity_size") in ("small", "micro"):
            nm += 0.35
        nm += {4: 0.3, 8: 0.15, 12: 0.0}.get(facts.get("fee_window"), 0.0)
        if m["live_family"]:
            nm -= 0.4  # owner kept siblings alive and dropped this one: likely deliberate
        non_merit = max(0.0, min(1.0, nm))
    else:
        non_merit = 0.5  # lived its full term; the question is whether the market came late

    words = m.get("shortest_claim_words")
    claim_breadth = 0.5 if words is None else max(0.0, min(1.0, (300 - words) / 200))
    family_breadth = min(1.0, m["family_countries"] / 4)
    breadth = 0.7 * claim_breadth + 0.3 * family_breadth

    examiner = _log_scale(m["fwd_examiner"], 10)

    clear = 1.0
    if m["live_family"]:
        clear -= 0.6
    clear -= {"high": 0.4, "medium": 0.2}.get(regulatory_burden, 0.0)
    if facts.get("revival_risk"):
        clear -= 0.3
    clear = max(0.0, clear)

    return {
        "field_alive": field_alive,
        "momentum": momentum,
        "non_merit_death": non_merit,
        "breadth": breadth,
        "examiner_relevance": examiner,
        "clear_path": clear,
    }


def score(facts: dict, m: dict, regulatory_burden: str = "low") -> dict:
    comps = components(facts, m, regulatory_burden)
    total = round(sum(WEIGHTS[k] * v for k, v in comps.items()))

    # Confidence reflects how much evidence the score stands on, not how high it is.
    points = 0
    points += 2 if m["fwd_total"] >= 15 else (1 if m["fwd_total"] >= 4 else 0)
    points += 1 if facts.get("lapse_source") and "estimated" not in facts["lapse_source"] else 0
    points += 1 if facts.get("entity_size") else 0
    points += 1 if m.get("shortest_claim_words") else 0
    if facts["status"] == "expired_term" and not facts.get("status_inferred"):
        points += 1  # term expiry is a date, not a judgement call
    if facts.get("revival_risk"):
        points -= 1
    confidence = "high" if points >= 4 else ("medium" if points >= 2 else "low")

    if total >= 60:
        verdict = "Dead patent with a future"
    elif total >= 40:
        verdict = "Worth a closer look"
    else:
        verdict = "Probably deserved to die"

    return {
        "score": total,
        "confidence": confidence,
        "verdict": verdict,
        "components": {k: {"label": LABELS[k], "weight": WEIGHTS[k], "value": round(v, 2),
                           "points": round(WEIGHTS[k] * v, 1)} for k, v in comps.items()},
    }
