"""Prior-art benchmark (brief question 3): does the agent find what the examiner found?

Takes recently granted public US patents, hides their citation lists, gives the agent
only the title, abstract and first claim, and limits the search to documents with an
earlier priority date. Scores how many of the examiner's own US citations land in the
agent's top 10, against a single keyword search over the same corpus.

    python scripts/run_benchmark.py --targets 10
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graveyard import config, db, gp, llm  # noqa: E402
from graveyard.agents import prior_art  # noqa: E402
from graveyard.agents.prior_art import norm_pub  # noqa: E402

TARGETS_PATH = config.BENCHMARK_DIR / "targets.json"
RESULTS_PATH = config.BENCHMARK_DIR / "results.json"


def load_cached_records(skip: set[str]) -> list[dict]:
    out = []
    for p in (config.CACHE_DIR / "parsed").glob("*.json"):
        if p.stem in skip:
            continue
        out.append(json.loads(p.read_text("utf-8")))
    return out


def truth_of(rec: dict) -> list[str]:
    """Examiner-cited US references with a priority date before the target's (the search can only reach those)."""
    cut = rec.get("priority_date") or "9999"
    return sorted({b["pub"] for b in rec.get("backward", [])
                   if b["examiner"] and b["pub"].startswith("US") and (b.get("priority_date") or "9999") < cut})


def describe(rec: dict) -> str:
    claim = rec.get("claims", {}).get("independent", [""])[0] or rec.get("claims", {}).get("first", "")
    return f"Title: {rec['title']}\n\nAbstract: {rec['abstract']}\n\nFirst claim: {claim}"


def pick_targets(con, n: int, min_truth: int = 3, max_truth: int = 30, max_fetch: int = 60) -> list[dict]:
    """Recent US grants that cite patents in our sample, spread across classes."""
    by_class: dict[str, list[str]] = {}
    for r in con.execute("SELECT record, tech_class FROM patents"):
        rec = json.loads(r["record"])
        for f in rec.get("forward", []):
            if f["pub"].startswith("US") and f["pub"][-2:] in ("B1", "B2") and (f.get("priority_date") or "") >= "2019-01-01":
                by_class.setdefault(r["tech_class"], []).append(f["pub"])
    for c in by_class:
        by_class[c] = sorted(set(by_class[c]), key=lambda p: hashlib.md5(p.encode()).hexdigest())
    targets, fetched = [], 0
    classes = sorted(by_class)
    while len(targets) < n and fetched < max_fetch and any(by_class.values()):
        for c in classes:
            if len(targets) >= n or not by_class[c]:
                continue
            pub = by_class[c].pop(0)
            if any(t["pub"] == pub for t in targets):
                continue
            try:
                was_cached = gp.is_cached(pub)
                rec = gp.get_patent(pub)
                fetched += 0 if was_cached else 1
            except Exception as e:
                print(f"[target] {pub}: {type(e).__name__}")
                continue
            truth = truth_of(rec)
            # 3-30 examiner references: enough to score, few enough that a top 10 can matter
            if not min_truth <= len(truth) <= max_truth or not rec.get("abstract") or not rec.get("priority_date"):
                continue
            family = {a["pub"] for a in rec.get("family_apps", []) if a.get("pub")} | {pub}
            targets.append({
                "pub": pub, "title": rec["title"], "tech_class": c, "priority_date": rec["priority_date"],
                "input": describe(rec), "exclude": sorted(family), "examiner_refs": truth,
            })
            print(f"[target] {c} {pub} ({len(truth)} examiner refs): {rec['title'][:70]}")
    return targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=int, default=10)
    ap.add_argument("--reuse-targets", action="store_true", help="keep the existing targets.json")
    args = ap.parse_args()
    config.BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    con = db.connect()

    if args.reuse_targets and TARGETS_PATH.exists():
        targets = json.loads(TARGETS_PATH.read_text("utf-8"))
        for t in targets:  # recompute ground truth from the cached target page
            t["examiner_refs"] = truth_of(gp.get_patent(t["pub"]))
        targets = [t for t in targets if len(t["examiner_refs"]) >= 3]
    else:
        targets = pick_targets(con, args.targets)
    if not targets:
        sys.exit("No targets found: build the sample first.")

    # Pooled corpus (as in CLEF-IP style prior-art benchmarks): our cached pages and their citation
    # rows, minus every target's own page; then each target's whole citation table (examiner AND
    # applicant references) is mixed in as title-only rows, the same shape as most other documents.
    skip = {p for t in targets for p in t["exclude"]}
    n_base = db.build_corpus(con, load_cached_records(skip))
    pooled = [b for t in targets for b in gp.get_patent(t["pub"]).get("backward", [])]
    n_pooled = db.add_corpus_rows(con, pooled)
    n_docs = con.execute("SELECT COUNT(*) FROM corpus").fetchone()[0]
    backend = prior_art.LocalBackend(con)
    in_corpus_norm = {norm_pub(r[0]) for r in con.execute("SELECT pub FROM corpus")}
    print(f"Corpus: {n_docs} documents ({n_base} from our sample's neighborhood, {n_pooled} pooled from target citation tables)")

    usage = llm.Usage()
    rows, modes = [], set()
    for t in targets:
        before = t["priority_date"].replace("-", "")
        truth = {norm_pub(p) for p in t["examiner_refs"]}
        agent = prior_art.run(t["input"], before, set(t["exclude"]), backend=backend, usage=usage)
        modes.add((agent["plan"]["mode"], agent["rank_mode"]))
        base = prior_art.baseline(t["input"], before, set(t["exclude"]), backend=backend)
        a_hits = sum(1 for r in agent["results"] if norm_pub(r["pub"]) in truth)
        b_hits = sum(1 for r in base if norm_pub(r["pub"]) in truth)
        ceiling = len(truth & in_corpus_norm)
        rows.append({"pub": t["pub"], "title": t["title"], "priority_date": t["priority_date"], "truth_n": len(truth),
                     "in_corpus": ceiling, "agent_hits": a_hits, "baseline_hits": b_hits})
        t["saved_run"] = agent
        t["run_at"] = datetime.now(timezone.utc).date().isoformat()
        print(f"{t['pub']}: truth {len(truth)}, in corpus {ceiling}, agent {a_hits}, keyword {b_hits} "
              f"({agent['plan']['mode']}, {agent['rank_mode']})", flush=True)

    truth_total = sum(r["truth_n"] for r in rows)
    summary = {
        "n_targets": len(rows),
        "truth_total": truth_total,
        "in_corpus_total": sum(r["in_corpus"] for r in rows),
        "agent_hits": sum(r["agent_hits"] for r in rows),
        "baseline_hits": sum(r["baseline_hits"] for r in rows),
        "agent_recall": sum(r["agent_hits"] for r in rows) / truth_total,
        "baseline_recall": sum(r["baseline_hits"] for r in rows) / truth_total,
        "agent_success": sum(1 for r in rows if r["agent_hits"]),
        "baseline_success": sum(1 for r in rows if r["baseline_hits"]),
    }
    method = [
        f"Targets: {len(rows)} US patents with priority dates from 2019 on, each citing a patent in our graveyard sample, "
        "each with 3 to 30 examiner-cited US references.",
        "Input: title, abstract and first independent claim only. The agent never sees the citation list.",
        "Search space: documents with a priority date before the target's, excluding the target and its family.",
        f"Corpus: {n_docs:,} US documents. {n_base:,} come from our sample's citation neighborhood (cached pages and the "
        f"documents they cite or are cited by; target pages excluded). The other {n_pooled:,} are the targets' full "
        "citation tables, examiner and applicant references alike, pooled in as title-only rows like most of the corpus. "
        "This is a pooled benchmark, not a search of every US patent.",
        "Ground truth: references marked as examiner-cited on the patent record, US documents with an earlier "
        "priority date than the target.",
        "Comparison: one keyword search built from the description's most frequent terms, same corpus, same cutoffs.",
    ]
    if all(m == ("keywords", "fusion") for m in modes):
        method.append("This run had no Claude access, so the agent used keyword planning and fusion without reranking.")
    earlier = config.BENCHMARK_DIR / "results_run1.json"
    if earlier.exists():
        s1 = json.loads(earlier.read_text("utf-8"))["summary"]
        method.append(f"An earlier run on the same targets, before we fixed how the search tool reads boolean queries "
                      f"(it had dropped phrases and ANDs), found {s1['agent_hits']} of {s1['truth_total']} "
                      f"({s1['agent_recall']:.0%}). Prompts were not changed between runs.")
    result = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backend": backend.name,
        "model": config.MODEL if any(m != ("keywords", "fusion") for m in modes) else None,
        "cost_usd": usage.total_cost,
        "summary": summary,
        "targets": rows,
        "method": method,
    }
    RESULTS_PATH.write_text(json.dumps(result, indent=1), "utf-8")
    TARGETS_PATH.write_text(json.dumps(targets, indent=1, default=str), "utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
