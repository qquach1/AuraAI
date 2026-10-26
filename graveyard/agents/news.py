"""News agent: recent M&A, licensing, partnership and regulatory events in a field.

Claude searches the web and reports only events a page it found actually describes, each
with a date and a source URL. Results are saved to data/news.json so the dashboard reads
them offline; anything without a valid URL and date is dropped.
"""

import json
import re
from datetime import date, datetime, timezone

from .. import config, llm
from .report import scrub

NEWS_PATH = config.DATA_DIR / "news.json"
TYPES = ["M&A", "Licensing", "Partnership", "Regulatory", "Litigation", "Funding"]

SYSTEM = (
    "You track patent and technology deal flow for early-stage founders. Search the web for "
    "recent, real events and report only what a page you found actually says. Each event needs "
    "the publication or event date and the URL of the page. Prefer company press releases, "
    "regulators, court or patent-office notices and established trade press. Do not guess "
    "dates, deal values or company names. Never characterize anything as infringing or free to use."
)


def fetch(field_label: str, cpc: str, usage=None, n: int = 5) -> list[dict]:
    """Recent events for one field via Claude web search. Returns validated items, newest first."""
    # 18 months back; dynamic filtering repeats searches, so allow enough for dates to be confirmed
    m = config.AS_OF.year * 12 + config.AS_OF.month - 1 - 18
    since = date(m // 12, m % 12 + 1, 1).isoformat()
    text = llm.web_research(
        "news", SYSTEM,
        f"Field: {field_label} (CPC {cpc}). Find up to {n} distinct events from {since} to "
        f"{config.AS_OF.isoformat()}: patent licensing deals, acquisitions of companies or patent "
        "portfolios, technology partnerships, patent litigation outcomes, and regulatory or patent-office "
        "decisions that change what founders in this field can build. Finish with a JSON object in a "
        '```json block: {"events": [{"type": "M&A" | "Licensing" | "Partnership" | "Regulatory" | '
        '"Litigation" | "Funding", "date": "YYYY-MM-DD or YYYY-MM", "headline": "under 15 words", '
        '"summary": "one sentence on why it matters to a founder", "companies": ["..."], '
        '"url": "https://...", "source": "publication or site name"}]}\n'
        "Use the article's publication date (the search result's page date is fine; give just YYYY-MM "
        "if only the month is known). Leave out an event rather than guess its date. Do not spend "
        "searches re-confirming dates you already have.",
        usage, max_uses=8)
    data = llm.extract_json(text) or {}
    out, seen = [], set()
    for e in data.get("events", []):
        url, when = e.get("url", ""), (e.get("date") or "").strip()
        precision = "day"
        if re.fullmatch(r"\d{4}-\d{2}", when):
            when, precision = when + "-01", "month"
        if not url.startswith("http") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when) or url in seen:
            continue
        if when > config.AS_OF.isoformat():
            continue
        seen.add(url)
        out.append({
            "type": e.get("type") if e.get("type") in TYPES else "Partnership",
            "date": when,
            "date_precision": precision,
            "headline": scrub(e.get("headline", "")).strip(),
            "summary": scrub(e.get("summary", "")).strip(),
            "companies": [c for c in e.get("companies", []) if isinstance(c, str)][:4],
            "url": url,
            "source": e.get("source", ""),
            "field": cpc,
            "field_label": field_label,
        })
    return sorted(out, key=lambda x: x["date"], reverse=True)


def load() -> dict:
    if NEWS_PATH.exists():
        return json.loads(NEWS_PATH.read_text("utf-8"))
    return {"fields": {}}


def save_field(cpc: str, label: str, items: list[dict], cost: float):
    data = load()
    data["fields"][cpc] = {"label": label, "items": items, "cost_usd": round(cost, 4),
                           "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    NEWS_PATH.write_text(json.dumps(data, indent=1), "utf-8")


def all_items(fields: list[str] | None = None) -> list[dict]:
    data = load()["fields"]
    items = [i for code, f in data.items() if not fields or code in fields for i in f["items"]]
    return sorted(items, key=lambda x: x["date"], reverse=True)
