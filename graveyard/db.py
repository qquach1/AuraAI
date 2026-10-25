"""SQLite store for the patent graveyard. One row per patent plus a full-text index."""

import json
import re
import sqlite3

from . import checklist, classes, config, derive, scoring

SCHEMA = """
CREATE TABLE IF NOT EXISTS patents (
    pub TEXT PRIMARY KEY,
    title TEXT,
    abstract TEXT,
    assignee TEXT,
    tech_class TEXT,          -- CPC subclass, e.g. A61B
    tech_label TEXT,          -- friendly name of that subclass
    cpc_first TEXT,
    status TEXT,              -- lapsed_fees | expired_term | in_force | expired_other | unknown
    end_date TEXT,            -- lapse date or term end
    end_year INTEGER,
    fee_window INTEGER,
    entity_size TEXT,
    priority_date TEXT,
    grant_date TEXT,
    score INTEGER,
    confidence TEXT,
    verdict TEXT,
    fwd_total INTEGER,
    fwd_after_end_unrelated INTEGER,
    fwd_recent INTEGER,
    revival_risk INTEGER,
    facts TEXT,               -- JSON from derive.status_facts
    metrics TEXT,             -- JSON from derive.citation_metrics
    scoring TEXT,             -- JSON from scoring.score
    record TEXT               -- full parsed Google Patents record
);
CREATE VIRTUAL TABLE IF NOT EXISTS patents_fts USING fts5(
    pub UNINDEXED, title, abstract, claims, cpc, assignee, tokenize='porter'
);
-- Prior-art search corpus: every cached patent page plus every document those pages cite
-- or are cited by (title, date and owner; abstract when we have the page).
CREATE TABLE IF NOT EXISTS corpus (
    pub TEXT PRIMARY KEY, title TEXT, priority_date TEXT, assignee TEXT, abstract TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts USING fts5(
    pub UNINDEXED, title, abstract, tokenize='porter'
);
"""


def connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or config.DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(patents)")}
    for col, typ in (("tech_label", "TEXT"), ("fwd_recent", "INTEGER")):  # databases built before these existed
        if col not in cols:
            con.execute(f"ALTER TABLE patents ADD COLUMN {col} {typ}")
            con.commit()
    return con


def build_row(rec: dict, tech_class: str | None = None) -> dict:
    facts = derive.status_facts(rec)
    metrics = derive.citation_metrics(rec, facts)
    cpc_codes = [c["code"] for c in rec.get("cpc", [])]
    sc = scoring.score(facts, metrics, checklist.burden(cpc_codes))
    first = rec.get("cpc_first") or (cpc_codes[0] if cpc_codes else "")
    assignee = (rec.get("assignee_current") or rec.get("assignee_original") or [""])[0]
    tech_class = tech_class or (first[:4] if first else None)
    return {
        "pub": rec["pub"],
        "title": rec.get("title", ""),
        "abstract": rec.get("abstract", ""),
        "assignee": assignee,
        "tech_class": tech_class,
        "tech_label": classes.label(tech_class, rec.get("cpc_subclass_desc")),
        "cpc_first": first,
        "status": facts["status"],
        "end_date": facts["end_date"],
        "end_year": facts["end_year"],
        "fee_window": facts["fee_window"],
        "entity_size": facts["entity_size"],
        "priority_date": facts["priority_date"],
        "grant_date": facts["grant_date"],
        "score": sc["score"],
        "confidence": sc["confidence"],
        "verdict": sc["verdict"],
        "fwd_total": metrics["fwd_total"],
        "fwd_after_end_unrelated": metrics["fwd_after_end_unrelated"],
        "fwd_recent": metrics["fwd_recent"],
        "revival_risk": int(bool(facts["revival_risk"])),
        "facts": json.dumps(facts),
        "metrics": json.dumps(metrics),
        "scoring": json.dumps(sc),
        "record": json.dumps(rec),
    }


def upsert(con: sqlite3.Connection, rec: dict, tech_class: str | None = None) -> dict:
    row = build_row(rec, tech_class)
    cols = ", ".join(row)
    qs = ", ".join("?" for _ in row)
    con.execute(f"INSERT OR REPLACE INTO patents ({cols}) VALUES ({qs})", list(row.values()))
    con.execute("DELETE FROM patents_fts WHERE pub = ?", (row["pub"],))
    claims = " ".join(rec.get("claims", {}).get("independent", []))
    cpc_text = " ".join(f"{c['code']} {c['desc']}" for c in rec.get("cpc", []))
    con.execute(
        "INSERT INTO patents_fts (pub, title, abstract, claims, cpc, assignee) VALUES (?, ?, ?, ?, ?, ?)",
        (row["pub"], row["title"], row["abstract"], claims, cpc_text, row["assignee"]),
    )
    return row


def rescore_all(con: sqlite3.Connection) -> int:
    """Recompute derived columns from stored records (after a scoring or checklist change)."""
    n = 0
    for r in con.execute("SELECT record, tech_class FROM patents").fetchall():
        upsert(con, json.loads(r["record"]), r["tech_class"])
        n += 1
    con.commit()
    return n


_STOP = set("""a an and are as at be by can for from has have how in into is it its of on or that the their
this to was we what when where which who will with you your i my me our they them do does using use used
based system method methods apparatus device devices thing things""".split())


def _fts_query(text: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", text.lower()) if len(w) > 1 and w not in _STOP]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words[:24]))


def search(con: sqlite3.Connection, text: str = "", tech_classes=None, statuses=None,
           end_years=None, min_score: int = 0, limit: int = 200) -> list[sqlite3.Row]:
    where, args = [], []
    if tech_classes:
        where.append(f"p.tech_class IN ({','.join('?' * len(tech_classes))})")
        args += list(tech_classes)
    if statuses:
        where.append(f"p.status IN ({','.join('?' * len(statuses))})")
        args += list(statuses)
    if end_years:
        where.append("p.end_year BETWEEN ? AND ?")
        args += [end_years[0], end_years[1]]
    if min_score:
        where.append("p.score >= ?")
        args.append(min_score)
    q = _fts_query(text) if text and text.strip() else ""
    if q:
        sql = (
            "SELECT p.*, bm25(patents_fts, 0, 10.0, 4.0, 2.0, 1.0, 1.0) AS rank FROM patents_fts "
            "JOIN patents p ON p.pub = patents_fts.pub WHERE patents_fts MATCH ?"
        )
        args = [q] + args
        if where:
            sql += " AND " + " AND ".join(where)
        sql += " ORDER BY rank LIMIT ?"
    else:
        sql = "SELECT p.*, 0 AS rank FROM patents p"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.score DESC LIMIT ?"
    args.append(limit)
    return con.execute(sql, args).fetchall()


def build_corpus(con: sqlite3.Connection, records: list[dict]) -> int:
    """Rebuild the prior-art corpus from parsed patent records and their citation rows."""
    docs: dict[str, dict] = {}
    utility = re.compile(r"^US(RE)?\d")  # skip design (USD) and plant (USPP) patents
    for rec in records:
        for c in rec.get("backward", []) + rec.get("forward", []) + rec.get("backward_family", []) + rec.get("forward_family", []):
            if utility.match(c["pub"]) and c["pub"] not in docs:
                docs[c["pub"]] = {"title": c["title"], "priority_date": c.get("priority_date"),
                                  "assignee": c.get("assignee", ""), "abstract": ""}
    for rec in records:  # full pages win over citation rows
        if utility.match(rec.get("pub", "")):
            docs[rec["pub"]] = {"title": rec.get("title", ""), "priority_date": rec.get("priority_date"),
                                "assignee": (rec.get("assignee_original") or [""])[0], "abstract": rec.get("abstract", "")}
    con.execute("DELETE FROM corpus")
    con.execute("DELETE FROM corpus_fts")
    con.executemany("INSERT INTO corpus VALUES (?, ?, ?, ?, ?)",
                    [(p, d["title"], d["priority_date"], d["assignee"], d["abstract"]) for p, d in docs.items()])
    con.executemany("INSERT INTO corpus_fts (pub, title, abstract) VALUES (?, ?, ?)",
                    [(p, d["title"], d["abstract"]) for p, d in docs.items()])
    con.commit()
    return len(docs)


def add_corpus_rows(con: sqlite3.Connection, rows: list[dict]) -> int:
    """Add citation rows (title, date, owner; no abstract) to the corpus if not already there."""
    have = {r[0] for r in con.execute("SELECT pub FROM corpus")}
    new = [r for r in rows if r["pub"] not in have and re.match(r"^US(RE)?\d", r["pub"])]
    new = list({r["pub"]: r for r in new}.values())
    con.executemany("INSERT INTO corpus VALUES (?, ?, ?, ?, '')",
                    [(r["pub"], r["title"], r.get("priority_date"), r.get("assignee", "")) for r in new])
    con.executemany("INSERT INTO corpus_fts (pub, title, abstract) VALUES (?, ?, '')",
                    [(r["pub"], r["title"]) for r in new])
    con.commit()
    return len(new)


def to_fts_boolean(query: str) -> str:
    """Examiner-style boolean query (quotes, AND/OR/NOT, parentheses, prefix*) -> FTS5 syntax.
    Hyphenated words become phrases; filler words are dropped."""
    q = query.replace("“", '"').replace("”", '"')
    out = []
    for t in re.findall(r'"[^"]+"|\(|\)|\b(?:AND|OR|NOT)\b|[A-Za-z0-9][A-Za-z0-9\-]*\*?', q):
        if t in ("AND", "OR", "NOT", "(", ")"):
            out.append(t)
            continue
        words = [w for w in re.findall(r"[A-Za-z0-9]+", t.lower()) if w not in _STOP]
        if not words:
            continue
        if t.startswith('"') or len(words) > 1:
            out.append('"' + " ".join(words) + '"')
        else:
            out.append(words[0] + ("*" if t.endswith("*") else ""))
    return " ".join(out)


def search_corpus(con: sqlite3.Connection, text: str, before: str | None = None, limit: int = 30,
                  boolean: bool = False) -> list[dict]:
    q = to_fts_boolean(text) if boolean else _fts_query(text)
    if not q:
        return []
    sql = ("SELECT c.*, bm25(corpus_fts, 0, 3.0, 1.0) AS rank FROM corpus_fts JOIN corpus c ON c.pub = corpus_fts.pub "
           "WHERE corpus_fts MATCH ?")
    args: list = [q]
    if before:
        sql += " AND c.priority_date IS NOT NULL AND c.priority_date < ?"
        args.append(f"{before[:4]}-{before[4:6]}-{before[6:]}")
    sql += " ORDER BY rank LIMIT ?"
    args.append(limit)
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def get(con: sqlite3.Connection, pub: str) -> dict | None:
    r = con.execute("SELECT * FROM patents WHERE pub = ?", (pub,)).fetchone()
    if not r:
        return None
    out = dict(r)
    for k in ("facts", "metrics", "scoring", "record"):
        out[k] = json.loads(out[k])
    return out


def class_labels(con: sqlite3.Connection) -> dict[str, str]:
    return {r["tech_class"]: r["tech_label"] for r in
            con.execute("SELECT DISTINCT tech_class, tech_label FROM patents WHERE tech_class IS NOT NULL")}


def stats(con: sqlite3.Connection) -> dict:
    rows = con.execute(
        "SELECT tech_class, status, COUNT(*) n FROM patents GROUP BY tech_class, status"
    ).fetchall()
    total = sum(r["n"] for r in rows)
    yr = con.execute("SELECT MIN(end_year), MAX(end_year) FROM patents WHERE end_year IS NOT NULL").fetchone()
    return {"total": total, "rows": [dict(r) for r in rows], "year_min": yr[0], "year_max": yr[1]}
