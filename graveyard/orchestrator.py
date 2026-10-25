"""Orchestrator: runs the triage pipeline for one patent and caches the result.

Flow (left to right, then back): Scout -> Status -> Blocker -> Market (score) -> Report.
Agents never call each other; the orchestrator passes outputs along and every finding
goes through the shared evidence store. The Prior-art agent is a separate check.
"""

import json
import time
from datetime import datetime, timezone

from . import config, db, llm
from .agents import blocker, market, report, scout, status
from .agents.base import EvidenceStore, Trace


def report_path(pub: str):
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return config.REPORTS_DIR / f"{pub}.json"


def cached(pub: str) -> dict | None:
    p = report_path(pub)
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def run(con, pub: str, query: str | None = None, use_llm: bool = True, on_step=None, save: bool = True) -> dict:
    patent = db.get(con, pub)
    if not patent:
        raise KeyError(pub)
    store, trace, usage = EvidenceStore(), Trace(on_step), llm.Usage()
    t0 = time.monotonic()

    near = trace.run("Scout", f"Find similar dead patents{' for: ' + query if query else ''}",
                     scout.nearby, con, patent)
    st = trace.run("Status", "Expired, lapsed for unpaid fees, or still in force?", status.run, patent, store)
    bl = trace.run("Blocker", "Follow-on patents, family, regulatory exclusivity, revival risk",
                   blocker.run, patent, store, usage, use_llm)
    burden = (bl or {}).get("regulatory_burden", "low")
    mk = trace.run("Market", "Citation activity, companies in the space, revival score",
                   market.run, patent, store, burden, usage, use_llm)
    rp = trace.run("Report", "Write the triage report and the assumption to test first",
                   report.run, patent, store, st, bl or {"blockers": []}, mk, near, usage, use_llm)

    out = {
        "pub": pub,
        "title": patent["title"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": config.AS_OF.isoformat(),
        "model": config.MODEL if rp and rp.get("mode") == "claude" else None,
        "report": rp,
        "status": st,
        "blockers": bl,
        "market": mk,
        "nearby": near,
        "evidence": store.to_list(),
        "trace": trace.steps,
        "usage": {"calls": usage.calls, "total_cost_usd": usage.total_cost,
                  "seconds": round(time.monotonic() - t0, 1)},
    }
    if save:
        report_path(pub).write_text(json.dumps(out, indent=1, default=str), "utf-8")
    return out
