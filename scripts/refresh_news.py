"""Refresh the dashboard's Deals & news feed: one Claude web search per field.

    python scripts/refresh_news.py                 # the ten seed fields
    python scripts/refresh_news.py --fields A61B H01M
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graveyard import classes, config, llm  # noqa: E402
from graveyard.agents import news  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fields", nargs="*", default=list(classes.TECH_CLASSES))
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if not config.llm_available():
        sys.exit("Needs ANTHROPIC_API_KEY.")

    def one(code):
        usage = llm.Usage()
        items = news.fetch(classes.label(code), code, usage)
        return code, items, usage.total_cost

    total = 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for fut in as_completed([pool.submit(one, c) for c in args.fields]):
            code, items, cost = fut.result()
            total += cost
            news.save_field(code, classes.label(code), items, cost)  # main thread only: no write races
            print(f"{code} {classes.label(code)}: {len(items)} events ${cost:.3f}", flush=True)
    print(f"Done. Model cost ${total:.2f}")


if __name__ == "__main__":
    main()
