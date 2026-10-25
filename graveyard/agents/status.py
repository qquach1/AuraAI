"""Status agent: expired at term, lapsed for unpaid fees, or still in force.

Pure code over the recorded legal events. A lapse counts only when a maintenance-fee
expiration event is on record; a term end without an expiration event is an estimate.
"""

from .. import gp

WINDOW_TEXT = {4: "3.5-year (first)", 8: "7.5-year (second)", 12: "11.5-year (third)"}


def run(patent: dict, store) -> dict:
    f = patent["facts"]
    pub = patent["pub"]
    url = gp.patent_url(pub)
    ids = []

    if f["status"] == "lapsed_fees":
        win = WINDOW_TEXT.get(f["fee_window"], "a")
        conf = "high" if f["lapse_source"] and "estimated" not in f["lapse_source"] else "medium"
        ids.append(store.add(
            "status",
            f"{pub} lapsed on {f['lapse_date']} because the {win} maintenance fee was not paid.",
            url + "#legalEvents", f"Read from {f['lapse_source']}", conf,
            status=f["status"], lapse_date=f["lapse_date"], window=f["fee_window"],
        ))
        if f["fees_paid"]:
            paid = ", ".join(f"{y}th-year" for y in f["fees_paid"])
            ids.append(store.add("status", f"The owner paid the {paid} fee(s) before stopping.",
                                 url + "#legalEvents", "Maintenance-fee payment events", "high"))
        else:
            ids.append(store.add("status", "No maintenance fee was ever paid after grant.",
                                 url + "#legalEvents", "No payment events on record", "medium"))
        unused = None
        if f["term_end"] and f["lapse_date"]:
            unused = int(f["term_end"][:4]) - int(f["lapse_date"][:4])
            ids.append(store.add(
                "status", f"The owner gave up roughly {unused} years of remaining term (term would have ended {f['term_end']}).",
                url, "Term end from the expiration event, else filing date plus 20 years",
                "medium" if f["term_end_estimated"] else "high"))
        if f["revival_risk"]:
            ids.append(store.add(
                "status", f"The lapse is only {f['months_since_end']:.0f} months old, so the owner could still petition to revive it.",
                url + "#legalEvents", "Months since lapse", "high"))
        summary = f"Lapsed {f['lapse_date']} at the {win} fee window"
    elif f["status"] == "expired_term" and f.get("status_inferred"):
        ids.append(store.add(
            "status", f"{pub} appears to have reached the end of its term by {f['term_end']}. {f['status_inferred']}",
            url + "#events", "Expected expiration date compared with today; status not re-checked", "medium"))
        summary = f"Past its expected expiration {f['term_end']} (inferred)"
    elif f["status"] == "expired_term":
        ids.append(store.add(
            "status", f"{pub} reached the end of its full term on {f['term_end']}.",
            url + "#events", "Expiration event" if not f["term_end_estimated"] else "Filing date plus 20 years (estimate)",
            "medium" if f["term_end_estimated"] else "high"))
        if f["fees_paid"]:
            ids.append(store.add("status", "The owner paid every maintenance fee, so it was valued until the end.",
                                 url + "#legalEvents", "Maintenance-fee payment events", "high"))
        summary = f"Expired at full term {f['term_end']}"
    elif f["status"] == "in_force":
        ids.append(store.add(
            "status", f"{pub} appears to still be in force ({f['google_status'] or 'active'}"
            + (", reinstated after a lapse" if f["reinstated"] else "") + ").",
            url, "Legal status on record", "high"))
        summary = "Still in force" + (" (reinstated)" if f["reinstated"] else "")
    else:
        ids.append(store.add("status", f"Status is unclear: '{f['google_status']}'.", url, "Legal status on record", "low"))
        summary = "Status unclear"

    src = patent["record"].get("source") or "patents.google.com"
    ids.append(store.add("status", f"The public record behind these facts was retrieved from {src}.",
                         url, "Google Patents page (bibliographic data, USPTO legal events, citations)", "high"))

    if f["entity_size"]:
        ids.append(store.add(
            "status", f"At its last fee payment the owner claimed {f['entity_size']}-entity status.",
            url + "#legalEvents", "Entity code on the payment event (M1/M2/M3)", "high",
            entity=f["entity_size"]))

    return {"facts": f, "evidence": ids, "summary": summary}
