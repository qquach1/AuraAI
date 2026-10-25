"""Turn a parsed Google Patents record into status facts and citation metrics.

Everything here is plain code over public records, so every number in a report can be
traced back to a legal event or a citation row.
"""

import re
from datetime import date, timedelta

from . import config

YEAR = 365.25


def d(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    try:
        if re.fullmatch(r"\d{8}", s):
            return date(int(s[:4]), int(s[4:6]), int(s[6:]))
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def years_between(a: date, b: date) -> float:
    return (b - a).days / YEAR


# ---------------------------------------------------------------- status


def grant_date(rec: dict) -> date | None:
    for e in rec.get("events", []):
        if e["type"] == "granted" or e["title"].lower().startswith("application granted"):
            return d(e["date"])
    if rec.get("pub", "")[-2:] in ("B1", "B2"):
        return d(rec.get("publication_date"))
    return None


_ENTITY = {"1": "large", "2": "small", "3": "micro"}


def _event_text(le: dict) -> str:
    return (le["title"] + " " + " ".join(f"{k}: {v}" for k, v in le["attrs"].items())).upper()


def _entity_in(up: str) -> str | None:
    m = re.search(r"ORIGINAL EVENT CODE: ?M([123])55", up)
    if m:
        return _ENTITY[m.group(1)]
    m = re.search(r"ENTITY STATUS (?:OF PATENT OWNER: |SET TO )(SMALL|MICRO|LARGE|UNDISCOUNTED)", up)
    if m:
        return {"UNDISCOUNTED": "large"}.get(m.group(1), m.group(1).lower())
    for word in ("MICRO", "SMALL", "LARGE"):
        if f"{word} ENTITY" in up and "NO LONGER" not in up:
            return word.lower()
    return None


def fee_payments(rec: dict) -> list[dict]:
    """Maintenance fee payments with year (4/8/12) and entity size when recorded."""
    out = []
    for le in rec.get("legal_events", []):
        up = _event_text(le)
        if le["code"] not in ("FPAY", "MAFP") and "PAYMENT OF MAINTENANCE FEE" not in up:
            continue
        year = None
        m = re.search(r"YEAR OF FEE PAYMENT: ?(4|8|12)\b", up) or re.search(r"\b(4|8|12)(?:TH|ST|ND|RD)? ?(?:YR|YEAR)", up)
        if m:
            year = int(m.group(1))
        out.append({"date": le["date"], "year": year, "entity": _entity_in(up), "code": le["code"]})
    return out


def entity_size(rec: dict) -> str | None:
    """Latest entity size the owner claimed in any fee-related event."""
    ent = None
    for le in sorted(rec.get("legal_events", []), key=lambda x: x["date"] or ""):
        e = _entity_in(_event_text(le))
        if e:
            ent = e
    return ent


def _lapse_event(rec: dict) -> tuple[date | None, str | None]:
    """Date the patent lapsed for non-payment, and which record says so."""
    for le in rec.get("legal_events", []):
        txt = (le["title"] + " " + " ".join(le["attrs"].values())).upper()
        if le["code"] == "FP" or "LAPSED DUE TO FAILURE TO PAY" in txt:
            eff = le["attrs"].get("Effective date")
            return d(eff) or d(le["date"]), f"legal event {le['code']} on {le['date']}"
    for le in rec.get("legal_events", []):
        txt = (le["title"] + " " + " ".join(le["attrs"].values())).upper()
        if le["code"] == "LAPS" or "EXPIRED FOR FAILURE TO PAY" in txt or "EVENT CODE: EXP." in txt:
            eff = le["attrs"].get("Effective date")
            return d(eff) or d(le["date"]), f"legal event {le['code']} on {le['date']}"
    for e in rec.get("events", []):
        if "fee related" in e["title"].lower():
            return d(e["date"]), "status event 'Expired - Fee Related'"
    return None, None


def _reinstated(rec: dict, after: date | None) -> bool:
    for le in rec.get("legal_events", []):
        txt = (le["title"] + " " + " ".join(le["attrs"].values())).upper()
        if le["code"] in ("PRDP", "PRNP") or "REINSTATED" in txt or "EVENT CODE: PMFG" in txt:
            when = d(le["date"])
            if after is None or (when and when >= after):
                return True
    return False


def _expiration_event(rec: dict) -> date | None:
    best = None
    for e in rec.get("events", []):
        t = e["title"].lower()
        if "expiration" in t or "expired - lifetime" in t:
            when = d(e["date"])
            if when and (best is None or "adjusted" in t or "lifetime" in t):
                best = when
    return best


def status_facts(rec: dict) -> dict:
    gs = (rec.get("legal_status") or "").strip()
    granted = grant_date(rec)
    filed = d(rec.get("filing_date"))
    priority = d(rec.get("priority_date"))
    payments = fee_payments(rec)
    paid_years = sorted({p["year"] for p in payments if p["year"]})
    entity = entity_size(rec)

    term_end = _expiration_event(rec)
    term_end_estimated = False
    if not term_end and filed:
        term_end = filed + timedelta(days=round(20 * YEAR))
        term_end_estimated = True

    lapse_date, lapse_source = (None, None)
    status = "unknown"
    gl = gs.lower()
    if "fee related" in gl:
        status = "lapsed_fees"
        lapse_date, lapse_source = _lapse_event(rec)
    elif "lifetime" in gl:
        status = "expired_term"
    elif gl.startswith("active") or gl == "granted":
        status = "in_force"
    elif "reinstated" in gl:
        status = "in_force"
    elif gl.startswith("expired"):
        status = "expired_other"
    elif gl in ("ceased", "withdrawn", "abandoned"):
        status = "expired_other"

    reinstated = status == "lapsed_fees" and _reinstated(rec, lapse_date)
    if reinstated:
        status = "in_force"

    # An archived page can be older than the patent's death. If it still says Active but the
    # expected expiration date has passed, it is dead at least by term; flag the inference.
    status_inferred = None
    snap = re.search(r"snapshot (\d{8})", rec.get("source") or "")
    if status == "in_force" and term_end and term_end < config.AS_OF and not reinstated:
        status = "expired_term"
        status_inferred = (f"The record{' (archived ' + snap.group(1)[:4] + '-' + snap.group(1)[4:6] + ')' if snap else ''} "
                           f"still showed Active, but its expected expiration ({term_end.isoformat()}) has passed.")

    window = None
    if status == "lapsed_fees" and granted and lapse_date:
        y = years_between(granted, lapse_date)
        window = min((4, 8, 12), key=lambda w: abs(w - y))
    elif status == "lapsed_fees" and granted:
        # No dated lapse event: infer the window from the fees that were paid.
        window = {(): 4, (4,): 8, (4, 8): 12}.get(tuple(paid_years))
        lapse_date = granted + timedelta(days=round(window * YEAR)) if window else None
        lapse_source = "estimated from grant date and fees paid" if window else None

    died = lapse_date if status == "lapsed_fees" else (term_end if status == "expired_term" else None)
    months_since = (config.AS_OF - died).days / 30.44 if died else None

    return {
        "google_status": gs,
        "status": status,
        "grant_date": granted.isoformat() if granted else None,
        "priority_date": priority.isoformat() if priority else None,
        "filing_date": filed.isoformat() if filed else None,
        "lapse_date": lapse_date.isoformat() if lapse_date else None,
        "lapse_source": lapse_source,
        "fee_window": window,
        "fees_paid": paid_years,
        "entity_size": entity,
        "term_end": term_end.isoformat() if term_end else None,
        "term_end_estimated": term_end_estimated,
        "end_date": died.isoformat() if died else None,
        "end_year": died.year if died else None,
        "months_since_end": round(months_since, 1) if months_since is not None else None,
        # Lapsed patents can be revived by petition; risk is highest in the first two years.
        "revival_risk": status == "lapsed_fees" and months_since is not None and months_since < 24,
        "reinstated": reinstated,
        "status_inferred": status_inferred,
        "record_date": f"{snap.group(1)[:4]}-{snap.group(1)[4:6]}-{snap.group(1)[6:8]}" if snap else None,
    }


# ---------------------------------------------------------------- citations


_CORP_WORDS = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|gmbh|ag|sa|nv|bv|kk|"
    r"the|of|and|technologies|technology|holdings|international|group)\b\.?", re.I)


def norm_assignee(name: str) -> str:
    n = _CORP_WORDS.sub(" ", (name or "").lower())
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return " ".join(n.split()[:2])


def citation_metrics(rec: dict, facts: dict) -> dict:
    owners = {norm_assignee(a) for a in rec.get("assignee_original", []) + rec.get("assignee_current", [])}
    owners.discard("")
    fwd = rec.get("forward", [])
    seen = {f["pub"] for f in fwd}
    fwd_all = fwd + [f for f in rec.get("forward_family", []) if f["pub"] not in seen]

    end = d(facts.get("end_date"))
    recent_cut = config.AS_OF - timedelta(days=round(config.RECENT_YEARS * YEAR))
    # "Field still alive": unrelated citations after a lapse; for a full-term expiry, also
    # count its last five years of term, since a recent expiry leaves no time to cite it after.
    alive_cut = end
    if end and facts.get("status") == "expired_term":
        alive_cut = end - timedelta(days=round(5 * YEAR))
    by_year: dict[int, int] = {}
    after_end = after_end_unrelated = alive_unrelated = recent = examiner_fwd = 0
    recent_companies: dict[str, int] = {}
    same_owner_followons = []
    for f in fwd_all:
        pri = d(f["priority_date"]) or d(f["publication_date"])
        if not pri:
            continue
        by_year[pri.year] = by_year.get(pri.year, 0) + 1
        own = norm_assignee(f["assignee"])
        related = bool(own) and own in owners
        if end and pri > end:
            after_end += 1
            if not related:
                after_end_unrelated += 1
        if alive_cut and pri > alive_cut and not related:
            alive_unrelated += 1
        if pri >= recent_cut:
            recent += 1
            if f["assignee"] and not related:
                recent_companies[f["assignee"]] = recent_companies.get(f["assignee"], 0) + 1
        if f["examiner"]:
            examiner_fwd += 1
        if related:
            same_owner_followons.append(f)

    live_family = [
        a for a in rec.get("family_apps", [])
        if a.get("pub") and a["pub"] != rec.get("pub") and a.get("status", "").lower().startswith("active")
    ]
    claims = rec.get("claims", {})
    return {
        "fwd_total": len(fwd_all),
        "fwd_after_end": after_end,
        "fwd_after_end_unrelated": after_end_unrelated,
        "fwd_alive_unrelated": alive_unrelated,
        "fwd_recent": recent,
        "fwd_examiner": examiner_fwd,
        "fwd_by_year": dict(sorted(by_year.items())),
        "recent_companies": sorted(recent_companies.items(), key=lambda kv: -kv[1])[:8],
        "same_owner_followons": len(same_owner_followons),
        "bwd_total": len(rec.get("backward", [])),
        "bwd_examiner": sum(1 for b in rec.get("backward", []) if b["examiner"]),
        "family_countries": len(rec.get("family_countries", [])),
        "live_family": len(live_family),
        "claims_count": claims.get("count", 0),
        "shortest_claim_words": claims.get("shortest_independent_words"),
    }
