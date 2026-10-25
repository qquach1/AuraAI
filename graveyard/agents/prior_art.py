"""Prior-art agent: given a patent-style description, find the earlier patents an examiner
would cite (brief question 3).

Steps: break the description into claim elements and examiner-style queries (Claude), run
each query against patents filed before the cutoff date, fuse the ranked lists, follow
citations from the strongest hits, then have Claude rerank the pool to a top 10. Without
Claude it falls back to keyword queries and fusion order.
"""

import os
import re
import sqlite3
from collections import defaultdict

from .. import config, db, gp, llm

PLAN_SYSTEM = (
    "You are a USPTO patent examiner planning a prior-art search. Break the invention into its "
    "essential claim elements, then write boolean keyword queries the way an examiner would: "
    "each query targets one or two elements, uses OR for synonyms and quotes for phrases, and "
    "has 2 to 5 concept groups. Use vocabulary patent drafters use, not marketing words."
)
PLAN_SCHEMA = llm.obj({
    "elements": llm.arr(llm.STR),
    "queries": llm.arr(llm.obj({"query": llm.STR, "targets": llm.STR})),
})

RERANK_SYSTEM = (
    "You are a USPTO patent examiner. From a pool of earlier documents, pick the ones you "
    "would cite against the application: those that disclose its claim elements, alone or in "
    "combination. Judge only from the titles, snippets and dates given."
)
RERANK_SCHEMA = llm.obj({
    "ranked": llm.arr(llm.obj({"pub": llm.STR, "elements_disclosed": llm.STR, "why": llm.STR})),
})

STOP = set("""a an the and or of to in on for with by from as at is are be been being this that these those
which wherein whereby said such it its their into than then there thereof herein comprising comprises comprise
including includes having has have method system apparatus device means first second plurality one more least
based using used use configured provide provided providing least each other may can between within via""".split())


def norm_pub(pub: str) -> str:
    """US8123456B2 -> US8123456; US20100123456A1 -> US20100123456."""
    m = re.match(r"([A-Z]{2})0*(\d+)", (pub or "").replace(" ", ""))
    return f"{m.group(1)}{m.group(2)}" if m else pub


def _keywords(text: str, n: int) -> list[str]:
    words = [w for w in re.findall(r"[a-z][a-z\-]{2,}", text.lower()) if w not in STOP]
    freq = defaultdict(int)
    for w in words:
        freq[w] += 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], words.index(kv[0])))][:n]


def plan(description: str, usage=None, use_llm=True) -> dict:
    if use_llm and config.llm_available():
        out = llm.structured(
            "prior_art", PLAN_SYSTEM,
            f"Invention description:\n{description[:6000]}\n\nReturn 3-6 elements and 5-7 queries.",
            PLAN_SCHEMA, usage, effort="medium", max_tokens=6000)
        if out and out["queries"]:
            return {**out, "mode": "claude"}
    # Fallback: one query per part of the description (title, abstract opening, claim), plus top terms
    parts = dict(re.findall(r"(Title|Abstract|First claim):\s*(.+?)(?=\n\n[A-Z][a-z ]+:|\Z)", description, re.S))
    title = parts.get("Title", description[:120])
    abstract_open = re.split(r"(?<=[.;])\s", parts.get("Abstract", description))[0]
    claim = parts.get("First claim", "")
    queries = [" ".join(_keywords(title, 6)), " ".join(_keywords(abstract_open, 6)),
               " ".join(_keywords(claim, 6)), " ".join(_keywords(description, 5))]
    return {"elements": [], "queries": [{"query": q, "targets": "keywords"} for q in queries if q.strip()],
            "mode": "keywords"}


class GoogleBackend:
    name = "Google Patents (all US patents and applications)"

    def search(self, query: str, before: str | None, num: int = 30) -> list[dict]:
        res = gp.search(q=query, before_priority=before, country="US", status=None, ptype="PATENT", num=num)
        return res["results"]


class LocalBackend:
    """Full-text search over the local corpus: cached patent pages plus their citation rows."""

    def __init__(self, con):
        self.con = con
        n = con.execute("SELECT COUNT(*) FROM corpus").fetchone()[0]
        self.name = f"Local corpus ({n:,} US documents: cached pages and their citation lists)"

    def search(self, query: str, before: str | None, num: int = 30) -> list[dict]:
        # The boolean form keeps the examiner's phrases and ANDs (precise); the any-word form
        # catches what the boolean misses. Boolean hits come first.
        rows = []
        try:
            rows = db.search_corpus(self.con, query, before, limit=num, boolean=True)
        except sqlite3.OperationalError:
            pass  # query the FTS5 grammar rejects: fall back to any-word search
        seen = {r["pub"] for r in rows}
        text = re.sub(r"\b(AND|OR|NOT)\b|[()\"*]", " ", query)
        rows += [r for r in db.search_corpus(self.con, text, before, limit=num) if r["pub"] not in seen]
        return [{"pub": r["pub"], "title": r["title"], "snippet": (r["abstract"] or "")[:300],
                 "priority_date": r["priority_date"], "assignee": r["assignee"]} for r in rows[:num]]


def default_backend(con):
    """Local corpus by default (offline, repeatable); GS_SEARCH=google searches Google Patents live."""
    return GoogleBackend() if os.getenv("GS_SEARCH") == "google" and not config.OFFLINE else LocalBackend(con)


def run(description: str, before: str | None = None, exclude: set[str] | None = None, backend=None,
        k: int = 10, usage=None, use_llm: bool = True, chain: bool = True, on_step=None) -> dict:
    """before: priority cutoff YYYYMMDD. exclude: publications to drop (target and family)."""
    exclude_norm = {norm_pub(p) for p in (exclude or set())}
    backend = backend or GoogleBackend()
    chain = chain and isinstance(backend, GoogleBackend)
    log = []

    def step(msg):
        log.append(msg)
        if on_step:
            on_step(msg)

    p = plan(description, usage, use_llm)
    step(f"Planned {len(p['queries'])} queries ({p['mode']})")

    pool: dict[str, dict] = {}
    fused: dict[str, float] = defaultdict(float)
    for qi, q in enumerate(p["queries"]):
        try:
            results = backend.search(q["query"], before, num=50)
        except Exception as e:
            step(f"Query failed: {q['query']} ({type(e).__name__})")
            continue
        kept = 0
        for rank, r in enumerate(results):
            key = norm_pub(r["pub"])
            if key in exclude_norm or not r.get("pub"):
                continue
            pool.setdefault(key, {**r, "found_by": []})["found_by"].append(qi)
            fused[key] += 1.0 / (60 + rank)
            kept += 1
        step(f"Query {qi + 1}: {q['query']} -> {kept} results")

    if chain and fused:
        # Examiners follow citations from strong hits; do the same for the top three.
        for key in sorted(fused, key=fused.get, reverse=True)[:3]:
            try:
                rec = gp.get_patent(pool[key]["pub"])
            except Exception:
                continue
            added = 0
            for b in rec.get("backward", []):
                bk = norm_pub(b["pub"])
                if not b["pub"].startswith("US") or bk in exclude_norm:
                    continue
                if before and b.get("priority_date") and b["priority_date"].replace("-", "") >= before:
                    continue
                pool.setdefault(bk, {"pub": b["pub"], "title": b["title"], "snippet": "",
                                     "priority_date": b["priority_date"], "assignee": b["assignee"], "found_by": []})
                fused[bk] += 0.5 / (60 + 5) * (2 if b["examiner"] else 1)
                added += 1
            step(f"Followed citations of {pool[key]['pub']}: +{added}")

    ordered = sorted(fused, key=fused.get, reverse=True)
    shortlist = [pool[x] for x in ordered[:60]]  # what Claude reranks: titles are short, so 60 stays cheap
    ranked, mode = None, "fusion"
    if use_llm and config.llm_available() and shortlist:
        lines = "\n".join(f"- {c['pub']} | {c.get('priority_date')} | {c.get('assignee', '')} | {c['title']} | "
                          f"{(c.get('snippet') or '')[:220]}" for c in shortlist)
        out = llm.structured(
            "prior_art", RERANK_SYSTEM,
            f"Application:\n{description[:5000]}\n\nClaim elements: {'; '.join(p['elements'])}\n\n"
            f"Pool (pub | priority | owner | title | snippet):\n{lines}\n\nReturn your top {k}, best first.",
            RERANK_SCHEMA, usage, effort="medium", max_tokens=6000)
        if out:
            by = {norm_pub(c["pub"]): c for c in shortlist}
            ranked, taken = [], set()
            for r in out["ranked"]:
                key = norm_pub(r["pub"])
                if key in by and key not in taken:
                    taken.add(key)
                    ranked.append({**by[key], "why": r["why"], "elements_disclosed": r["elements_disclosed"]})
            # top up from fusion order if Claude returned fewer than k
            for c in shortlist:
                if len(ranked) >= k:
                    break
                if norm_pub(c["pub"]) not in taken:
                    taken.add(norm_pub(c["pub"]))
                    ranked.append(c)
            mode = "claude rerank"
    if ranked is None:
        ranked = shortlist
    step(f"Ranked {len(pool)} candidates ({mode})")
    return {"plan": p, "results": ranked[:k], "pool_size": len(pool), "backend": backend.name,
            "rank_mode": mode, "log": log}


def baseline(text: str, before: str | None, exclude: set[str], backend=None, k: int = 10) -> list[dict]:
    """Single keyword search over the same backend, no agent steps. The comparison system."""
    backend = backend or GoogleBackend()
    ex = {norm_pub(p) for p in exclude}
    q = " ".join(_keywords(text, 5))
    res = [r for r in backend.search(q, before, num=30) if norm_pub(r["pub"]) not in ex]
    return res[:k]
