"""Build the demo sample: lapsed and expired US patents across several technology classes.

Starts from a few well-known seed patents per class and walks their citation lists
(snowball sampling), keeping granted US patents from the 2000-2005 priority years that
are in the target CPC subclass and are dead (lapsed for fees, or expired at full term).
Every page is cached, so the script is resumable and the finished database works offline.

    python scripts/build_sample.py --per-class 35 --max-fetch 900
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graveyard import config, db, derive, gp  # noqa: E402

SEEDS = {
    "G06F": ["US6285999B1"],                              # PageRank
    "B33Y": ["US5121329A", "US4575330A"],                 # fused deposition modeling; stereolithography
    "H01M": ["US5910382A"],                               # LiFePO4 cathode
    "A61B": ["US5632272A"],                               # pulse oximetry signal processing
    "A61K": ["US5250534A", "US5013556A", "US6090382A"],   # sildenafil; long-circulating liposomes; anti-TNF antibody
    "G02B": ["US4725110A", "US6369954B1", "US5802236A"],  # fiber gratings; liquid lens; microstructured fiber
    "H04W": ["US5101501A"],                               # CDMA soft handoff
    "F03D": ["US5083039A"],                               # variable-speed wind turbine
    "A01N": ["US3799758A", "US4742060A", "US5395837A"],   # glyphosate; imidacloprid; azoxystrobin
    "C02F": ["US4632745A"],                               # electrodeionization
}

# Granted before 2011 (numbers below 8,000,000): continuations with old priority dates but
# recent grants are mostly still in force, so they waste fetches.
GRANT = re.compile(r"^US[67]\d{6}B[12]$")


def candidates(rec: dict) -> list[str]:
    out = []
    for c in rec.get("forward", []) + rec.get("forward_family", []) + rec.get("backward", []):
        if not GRANT.match(c["pub"]):
            continue
        pri = c.get("priority_date") or ""
        # 2000 to mid-2005 priorities are all dead by now: lapsed for fees or past full term
        if "2000-01-01" <= pri <= "2005-06-30":
            out.append(c["pub"])
    # deterministic shuffle so we don't only take the oldest citations
    return sorted(set(out), key=lambda p: hashlib.md5(p.encode()).hexdigest())


def in_class(rec: dict, cls: str) -> bool:
    return any(c["code"].startswith(cls) for c in rec.get("cpc", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=35)
    ap.add_argument("--max-fetch", type=int, default=900, help="cap on new page fetches")
    ap.add_argument("--classes", nargs="*", default=list(SEEDS))
    args = ap.parse_args()

    con = db.connect()
    have = {r["pub"]: r["tech_class"] for r in con.execute("SELECT pub, tech_class FROM patents")}
    kept = {c: sum(1 for v in have.values() if v == c) for c in args.classes}
    if have:
        print(f"Resuming with {len(have)} patents already in the database")
    frontier = {c: [] for c in args.classes}
    seen = set(have)
    fetched = 0
    t0 = time.monotonic()

    def get(pub):
        nonlocal fetched
        new = not gp.is_cached(pub)
        rec = gp.get_patent(pub)
        if new:
            fetched += 1
        return rec

    for cls in args.classes:
        for s in SEEDS[cls]:
            try:
                rec = get(s)
            except (gp.NotFound, gp.Blocked) as e:
                print(f"[seed] {cls} {s}: {e}")
                continue
            print(f"[seed] {cls} {s}: {rec['title'][:60]} | {rec['legal_status']} | in class: {in_class(rec, cls)} "
                  f"| {len(candidates(rec))} candidates")
            frontier[cls] += [p for p in candidates(rec) if p not in seen]
        # patents already kept also seed the walk
        for pub, c in have.items():
            if c == cls:
                frontier[cls] += [p for p in candidates(gp.get_patent(pub)) if p not in seen]

    stop = False
    while not stop and any(kept[c] < args.per_class and frontier[c] for c in args.classes):
        for cls in args.classes:
            if kept[cls] >= args.per_class or not frontier[cls]:
                continue
            pub = frontier[cls].pop(0)
            if pub in seen:
                continue
            seen.add(pub)
            if fetched >= args.max_fetch and not gp.is_cached(pub):
                stop = True
                break
            try:
                rec = get(pub)
            except gp.NotFound:
                continue
            except gp.Blocked as e:
                print(f"[stop] {e}")
                stop = True
                break
            except Exception as e:
                print(f"[skip] {pub}: {type(e).__name__}: {e}")
                continue
            facts = derive.status_facts(rec)
            # The marketplace covers every field: a dead patent found while walking one class is
            # kept under its own CPC subclass. Quotas count per walk so the sample stays spread out.
            first = rec.get("cpc_first") or (rec["cpc"][0]["code"] if rec.get("cpc") else "")
            home = cls if in_class(rec, cls) else first[:4] or None
            ok = home is not None and facts["status"] in ("lapsed_fees", "expired_term")
            if ok:
                db.upsert(con, rec, home)
                con.commit()
                kept[cls] += 1
                frontier[cls] += [p for p in candidates(rec) if p not in seen]
            el = time.monotonic() - t0
            print(f"[{fetched:4d} fetched {el / 60:5.1f}m] {cls} {pub} {facts['status']:<13} "
                  f"{'KEEP ' + home if ok else 'skip'} ({kept[cls]}/{args.per_class}) {rec['title'][:50]}",
                  flush=True)

    print("\nKept per class:", kept, "| new pages fetched:", fetched)
    print(db.stats(con))

    # Prior-art corpus from every cached page, minus benchmark targets (see run_benchmark.py)
    tp = config.BENCHMARK_DIR / "targets.json"
    skip = {p for t in json.loads(tp.read_text("utf-8")) for p in t["exclude"]} if tp.exists() else set()
    recs = [json.loads(p.read_text("utf-8")) for p in (config.CACHE_DIR / "parsed").glob("*.json") if p.stem not in skip]
    print("Prior-art corpus:", db.build_corpus(con, recs), "documents")


if __name__ == "__main__":
    main()
