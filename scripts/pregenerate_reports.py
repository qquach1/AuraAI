"""Pre-run the agents for the highest-scoring patents so the demo never waits on an API.

    python scripts/pregenerate_reports.py --top 2                # top 2 in each seed class
    python scripts/pregenerate_reports.py --pubs US6280785B1
    python scripts/pregenerate_reports.py --all --rules-only     # rule-based reports for every patent
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graveyard import classes, config, db, orchestrator  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=2, help="patents per technology class")
    ap.add_argument("--classes", nargs="*", default=list(classes.TECH_CLASSES))
    ap.add_argument("--pubs", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--rules-only", action="store_true", help="skip Claude even if a key is set")
    ap.add_argument("--force", action="store_true", help="re-run patents that already have a Claude report")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    con = db.connect()
    if args.pubs:
        pubs = args.pubs
    elif args.all:
        pubs = [r["pub"] for r in con.execute("SELECT pub FROM patents ORDER BY score DESC")]
    else:
        pubs = []
        for cls in args.classes:
            pubs += [r["pub"] for r in con.execute(
                "SELECT pub FROM patents WHERE tech_class = ? ORDER BY score DESC LIMIT ?", (cls, args.top))]

    use_llm = config.llm_available() and not args.rules_only
    todo = []
    for pub in pubs:
        existing = orchestrator.cached(pub)
        if existing and not args.force and (existing["report"]["mode"] == "claude" or not use_llm):
            continue
        todo.append(pub)
    print(f"{len(todo)} reports to run ({'Claude' if use_llm else 'rules'}), {len(pubs) - len(todo)} already done")

    def one(pub):
        return orchestrator.run(db.connect(), pub, use_llm=use_llm)  # one connection per thread

    total = 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(one, p): p for p in todo}
        for fut in as_completed(futures):
            pub = futures[fut]
            try:
                out = fut.result()
            except Exception as e:
                print(f"{pub}: FAILED {type(e).__name__}: {e}")
                continue
            cost = out["usage"]["total_cost_usd"]
            total += cost
            r = out["report"]
            print(f"{pub}: {r['score']}/100 {r['mode']} ${cost:.3f} {out['usage']['seconds']}s "
                  f"verifier removed {sum('Removed' in line for line in r['verifier_log'])}", flush=True)
    print(f"Done. Model cost ${total:.2f}")


if __name__ == "__main__":
    main()
