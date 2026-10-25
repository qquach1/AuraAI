"""Re-apply the report verifier's wording rules to saved reports, without calling Claude again.

Use after changing REWRITES in graveyard/agents/report.py.

    python scripts/reverify_reports.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graveyard import config  # noqa: E402
from graveyard.agents.report import scrub  # noqa: E402

# Undo rewrites from an earlier, over-eager rule set before applying the current rules.
UNDO = [
    (r"\byou may be able to (use|copy|make|sell) \(verify\)", r"you can \1"),
    (r"\bfreedom-to-operate \(not assessed\)", "freedom-to-operate"),
    (r"\b(not|n't|never|no longer)\b([^.;:]{0,25}?)possibly usable without a license \(verify\)", r"\1\2free to use"),
]
SKIP_KEYS = {"url", "source", "pub", "id", "evidence", "mode", "model", "severity", "confidence", "verdict",
             "disclaimer"}


def fix(x, key=None):
    if isinstance(x, str):
        if key in SKIP_KEYS:
            return x
        for pat, rep in UNDO:
            x = re.sub(pat, rep, x)
        return scrub(x)
    if isinstance(x, list):
        return [fix(v, key) for v in x]
    if isinstance(x, dict):
        return {k: fix(v, k) for k, v in x.items()}
    return x


def main():
    changed = 0
    for p in sorted(config.REPORTS_DIR.glob("*.json")):
        out = json.loads(p.read_text("utf-8"))
        new = dict(out)
        new["report"] = {**fix(out["report"]), "disclaimer": config.DISCLAIMER}
        if out.get("market"):
            new["market"] = {**out["market"], "read": fix(out["market"].get("read") or {}),
                             "web": fix(out["market"].get("web") or [])}
        if new != out:
            p.write_text(json.dumps(new, indent=1, default=str), "utf-8")
            changed += 1
            print(f"updated {p.stem}")
    print(f"{changed} report(s) updated")


if __name__ == "__main__":
    main()
