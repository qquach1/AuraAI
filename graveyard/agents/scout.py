"""Scout agent: finds candidate patents in the graveyard by class and keyword.

With Claude available it first expands a founder's plain-language query into the
technical terms patents actually use; the search itself is SQLite full-text ranking.
"""

from .. import classes, config, db, llm

SYSTEM = (
    "You help founders search a database of lapsed and expired US patents. Patents use "
    "formal technical vocabulary, so a founder's plain words often miss them. Given a "
    "search, return technical synonyms and closely related terms a patent drafter would "
    "use, and the CPC subclasses most likely to hold matching patents."
)

SCHEMA = llm.obj({
    "terms": llm.arr(llm.STR),
    "cpc_subclasses": llm.arr(llm.STR),
})


def expand(query: str, usage=None) -> dict:
    allowed = ", ".join(f"{k} ({v})" for k, v in classes.TECH_CLASSES.items())
    out = llm.structured(
        "scout", SYSTEM,
        f"Search: {query}\n\nReturn at most 10 single words or short phrases in `terms`. "
        f"`cpc_subclasses` must come from this list: {allowed}.",
        SCHEMA, usage, effort="low", max_tokens=2000,
    )
    if not out:
        return {"terms": [], "cpc_subclasses": []}
    out["cpc_subclasses"] = [c for c in out["cpc_subclasses"] if c in classes.TECH_CLASSES]
    return out


def search(con, query: str, tech_classes=None, statuses=None, end_years=None, min_score=0,
           use_llm: bool = True, usage=None, expansion: dict | None = None) -> dict:
    if expansion is None:
        expansion = {"terms": [], "cpc_subclasses": []}
        if query and use_llm and config.llm_available():
            expansion = expand(query, usage)
    text = " ".join([query] + expansion["terms"]) if query else ""
    rows = db.search(con, text, tech_classes, statuses, end_years, min_score)
    return {
        "rows": rows,
        "expansion": expansion,
        "summary": f"{len(rows)} candidates" + (f"; expanded with {', '.join(expansion['terms'][:6])}" if expansion["terms"] else ""),
    }


def nearby(con, patent: dict, limit: int = 5) -> dict:
    """Other dead patents in the sample that address a similar problem."""
    rows = db.search(con, patent["title"], [patent["tech_class"]], ["lapsed_fees", "expired_term"], limit=limit + 1)
    rows = [r for r in rows if r["pub"] != patent["pub"]][:limit]
    items = [{"pub": r["pub"], "title": r["title"], "score": r["score"], "status": r["status"],
              "end_year": r["end_year"]} for r in rows]
    return {"items": items, "summary": f"{len(items)} similar dead patents in {patent['tech_label']}"}
