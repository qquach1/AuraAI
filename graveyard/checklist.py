"""Loads the blocker checklist and matches rules to a patent's CPC codes."""

import json
from functools import lru_cache

from . import config

_RANK = {"low": 0, "medium": 1, "high": 2}


@lru_cache(maxsize=1)
def rules() -> list[dict]:
    return json.loads(config.CHECKLIST_PATH.read_text("utf-8"))["rules"]


def matching(cpc_codes: list[str]) -> list[dict]:
    codes = [c.replace(" ", "").replace("/", "") for c in cpc_codes]
    out = []
    for r in rules():
        if "all" in r["applies_to"] or any(c.startswith(p.replace("/", "")) for p in r["applies_to"] for c in codes):
            out.append(r)
    return out


def burden(cpc_codes: list[str]) -> str:
    level = 0
    for r in matching(cpc_codes):
        if "all" not in r["applies_to"]:
            level = max(level, _RANK[r["burden"]])
    return {0: "low", 1: "medium", 2: "high"}[level]
