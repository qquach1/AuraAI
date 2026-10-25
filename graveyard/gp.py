"""Google Patents client: fetch and parse patent pages, run searches.

Pages and search results are cached on disk, so every call after the first is offline.
Requests are rate limited to stay polite; this is for a few hundred pages, not bulk crawling.

Page source (GS_SOURCE): "google" fetches patents.google.com directly; "wayback" fetches
the latest Internet Archive snapshot of the same page; "auto" (default) tries Google and
falls back to the archive. If Google answers with its automated-traffic page we stop
asking Google for the rest of the session rather than retrying.
"""

import gzip
import hashlib
import html as html_lib
import json
import os
import re
import threading
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from . import config

BASE = "https://patents.google.com"
WAYBACK = "http://web.archive.org/web/20261231000000id_/"
USER_AGENT = "GraveyardShift/0.1 (hackathon research prototype; patent triage)"
SOURCE = os.getenv("GS_SOURCE", "auto")
MIN_INTERVAL_S = {"patents.google.com": 5.0, "web.archive.org": 4.5}

_lock = threading.Lock()
_last_request: dict[str, float] = {}
_google_blocked = False
_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})


class OfflineError(RuntimeError):
    pass


class Blocked(RuntimeError):
    """The site told us to stop (automated-traffic page or repeated 429s)."""


class NotFound(RuntimeError):
    pass


def _get(url: str, timeout: int = 60, retries: int = 3) -> requests.Response:
    if config.OFFLINE:
        raise OfflineError(f"offline mode: not fetching {url}")
    host = urllib.parse.urlparse(url).netloc
    for attempt in range(retries):
        with _lock:
            wait = MIN_INTERVAL_S.get(host, 2.0) - (time.monotonic() - _last_request.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            _last_request[host] = time.monotonic()
        try:
            resp = _session.get(url, timeout=timeout)
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
            continue
        if resp.status_code == 200:
            return resp
        if resp.status_code == 503 and b"automated queries" in resp.content:
            raise Blocked(f"{host} returned its automated-traffic page")
        if resp.status_code == 404:
            raise NotFound(url)
        if resp.status_code == 429:
            time.sleep(90 * (attempt + 1))
            continue
        if 400 <= resp.status_code < 500:
            resp.raise_for_status()
        time.sleep(10 * (attempt + 1))
    raise Blocked(f"{host} kept refusing after {retries} tries: {url}")


def _body(resp: requests.Response) -> str:
    raw = resp.content
    if raw[:2] == b"\x1f\x8b":  # archive snapshots keep the original gzip encoding
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def _cache_path(kind: str, key: str, suffix: str):
    d = config.CACHE_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}{suffix}"


# ---------------------------------------------------------------- patent pages


def fetch_html(pub: str) -> str:
    global _google_blocked
    path = _cache_path("pages", pub, ".html.gz")
    if path.exists():
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    html, origin = None, None
    if SOURCE in ("auto", "google") and not _google_blocked:
        try:
            html, origin = _body(_get(f"{BASE}/patent/{pub}/en")), "patents.google.com"
        except Blocked:
            _google_blocked = True
            if SOURCE == "google":
                raise
    if html is None:
        resp = _get(f"{WAYBACK}{BASE}/patent/{pub}/en")
        m = re.search(r"/web/(\d{14})", resp.url)
        html, origin = _body(resp), f"web.archive.org snapshot {m.group(1) if m else ''}".strip()
    if 'itemprop="publicationNumber"' not in html:
        raise NotFound(f"{pub}: page has no patent record")
    path.write_bytes(gzip.compress(html.encode("utf-8")))
    _cache_path("pages", pub, ".src").write_text(origin, "utf-8")
    return html


def page_source(pub: str) -> str | None:
    p = _cache_path("pages", pub, ".src")
    return p.read_text("utf-8") if p.exists() else None


def get_patent(pub: str, refresh: bool = False) -> dict:
    """Parsed patent record. Cached as JSON next to the raw page."""
    path = _cache_path("parsed", pub, ".json")
    if path.exists() and not refresh:
        return json.loads(path.read_text("utf-8"))
    rec = parse_patent(fetch_html(pub))
    rec["source"] = page_source(pub)
    path.write_text(json.dumps(rec), "utf-8")
    return rec


def is_cached(pub: str) -> bool:
    return _cache_path("parsed", pub, ".json").exists() or _cache_path("pages", pub, ".html.gz").exists()


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _ref_rows(soup, prop: str) -> list[dict]:
    rows = []
    for tr in soup.find_all("tr", itemprop=prop):
        pub = tr.find("span", itemprop="publicationNumber")
        if not pub:
            continue
        pri = tr.find("td", itemprop="priorityDate")
        pubd = tr.find("td", itemprop="publicationDate")
        asg = tr.find("span", itemprop="assigneeOriginal")
        title = tr.find("td", itemprop="title")
        rows.append({
            "pub": _text(pub),
            "examiner": tr.find("span", itemprop="examinerCited") is not None,
            "family_to_family": tr.find("span", itemprop="familyCited") is not None,
            "priority_date": _text(pri) or None,
            "publication_date": _text(pubd) or None,
            "assignee": _text(asg),
            "title": _text(title),
        })
    return rows


_DEP_CLAIM = re.compile(r"\b(of|in|to|by|with)\s+claims?\s+\d+|\bclaims?\s+\d+\b", re.I)


def _claims(soup) -> dict:
    sec = soup.find("section", itemprop="claims")
    if not sec:
        return {"count": 0, "first": "", "independent": [], "shortest_independent_words": None}
    claims = []
    for div in sec.select("div.claim[num]"):
        txt = _text(div)
        if txt:
            claims.append(txt)
    if not claims:  # some pages use claim-text without num attributes
        claims = [_text(d) for d in sec.select("div.claim-text")][:1]
    indep = [c for c in claims if not _DEP_CLAIM.search(c[:200].split(",", 1)[0] + c[:120])]
    if not indep and claims:
        indep = claims[:1]
    words = [len(c.split()) for c in indep]
    return {
        "count": len(claims),
        "first": claims[0] if claims else "",
        "independent": indep[:5],
        "shortest_independent_words": min(words) if words else None,
    }


def parse_patent(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    art = soup.find("article") or soup

    title_el = art.find("span", itemprop="title")
    status_el = soup.select_one("dd[itemprop=legalStatusIfi] span[itemprop=status]")

    def first_time(prop):
        el = soup.find("time", itemprop=prop)
        return el.get("datetime") if el else None

    events = []
    for dd in soup.find_all("dd", itemprop="events"):
        t = dd.find("time", itemprop="date")
        events.append({
            "date": t.get("datetime") if t else None,
            "title": _text(dd.find("span", itemprop="title")),
            "type": _text(dd.find("span", itemprop="type")),
            "critical": dd.find("span", itemprop="critical") is not None,
        })

    legal = []
    for tr in soup.find_all("tr", itemprop="legalEvents"):
        t = tr.find("time", itemprop="date")
        attrs = {}
        for p in tr.find_all("p", itemprop="attributes"):
            label = _text(p.find("strong", itemprop="label"))
            value = _text(p.find("span", itemprop="value"))
            attrs[label] = (attrs[label] + " | " + value) if label in attrs else value
        legal.append({
            "date": t.get("datetime") if t else None,
            "code": _text(tr.find("td", itemprop="code")),
            "title": _text(tr.find("td", itemprop="title")),
            "attrs": attrs,
        })

    # Classification paths: one <ul> per path, broadest code first. Current pages mark the leaf
    # and the first code; pages archived before ~2022 use itemprop="cpcs" with no markers, so the
    # last code in each path is the leaf and the first path is the main one.
    cpc_leaf, cpc_first, cpc_desc = [], None, {}
    for ul in soup.find_all("ul", itemprop=["classifications", "cpcs"]):
        items = []
        for li in ul.find_all("li", itemprop=["classifications", "cpcs"]):
            code = _text(li.find("span", itemprop="Code"))
            desc = _text(li.find("span", itemprop="Description"))
            if code:
                items.append((code, desc, li))
                if len(code) == 4:
                    cpc_desc[code] = desc
        if not items:
            continue
        leaves = [(c, dsc, li) for c, dsc, li in items if li.find("meta", itemprop="Leaf")] or [items[-1]]
        for code, desc, li in leaves:
            if all(x["code"] != code for x in cpc_leaf):
                cpc_leaf.append({"code": code, "desc": desc})
            if li.find("meta", itemprop="FirstCode") and not cpc_first:
                cpc_first = code
    if not cpc_first and cpc_leaf:
        cpc_first = cpc_leaf[0]["code"]

    family_apps = []
    for tr in soup.find_all("tr", itemprop="applications"):
        rep = tr.find("span", itemprop="representativePublication")
        family_apps.append({
            "application": _text(tr.find("span", itemprop="applicationNumber")),
            "status": _text(tr.find("span", itemprop="ifiStatus")),
            "pub": _text(rep) if rep else None,
            "priority_date": _text(tr.find("td", itemprop="priorityDate")) or None,
            "filing_date": _text(tr.find("td", itemprop="filingDate")) or None,
            "title": _text(tr.find("td", itemprop="title")),
        })
    child_apps = []
    for tr in soup.find_all("tr", itemprop="childApps"):
        rep = tr.find("span", itemprop="representativePublication")
        child_apps.append({
            "application": _text(tr.find("span", itemprop="applicationNumber")),
            "relation": _text(tr.find("span", itemprop="relationType")),
            "pub": _text(rep) if rep else None,
            "priority_date": _text(tr.find("td", itemprop="priorityDate")) or None,
            "filing_date": _text(tr.find("td", itemprop="filingDate")) or None,
            "title": _text(tr.find("td", itemprop="title")),
        })
    countries = sorted({_text(s) for s in soup.find_all("span", itemprop="countryCode")} - {""})

    abstract = _text(soup.find("section", itemprop="abstract"))
    abstract = re.sub(r"^Abstract\s+", "", abstract)

    return {
        "pub": _text(soup.find("dd", itemprop="publicationNumber")),
        "title": _text(title_el),
        "abstract": abstract,
        "claims": _claims(soup),
        "legal_status": _text(status_el),
        "priority_date": first_time("priorityDate"),
        "filing_date": first_time("filingDate"),
        "publication_date": first_time("publicationDate"),
        "inventors": [_text(d) for d in soup.find_all("dd", itemprop="inventor")],
        "assignee_current": [_text(d) for d in soup.find_all("dd", itemprop="assigneeCurrent")],
        "assignee_original": [_text(d) for d in soup.find_all("dd", itemprop="assigneeOriginal")],
        "cpc": cpc_leaf,
        "cpc_first": cpc_first,
        "cpc_subclass_desc": cpc_desc,
        "events": events,
        "legal_events": legal,
        "backward": _ref_rows(soup, "backwardReferencesOrig"),
        "backward_family": _ref_rows(soup, "backwardReferencesFamily"),
        "forward": _ref_rows(soup, "forwardReferencesOrig"),
        "forward_family": _ref_rows(soup, "forwardReferencesFamily"),
        "family_apps": family_apps,
        "child_apps": child_apps,
        "family_countries": countries,
        "prior_art_keywords": [_text(d) for d in soup.find_all("dd", itemprop="priorArtKeywords")],
    }


# ---------------------------------------------------------------- search


def search(q: str | None = None, cpc: str | None = None, before_priority: str | None = None,
           after_priority: str | None = None, country: str = "US", status: str | None = "GRANT",
           num: int = 100, page: int = 0, ptype: str | None = "PATENT") -> dict:
    """Google Patents search. Dates are YYYYMMDD. Returns {'total': int, 'results': [...]}."""
    params = []
    if q:
        params.append(("q", q))
    if cpc:
        params.append(("cpc", cpc))
    if country:
        params.append(("country", country))
    if before_priority:
        params.append(("before", f"priority:{before_priority}"))
    if after_priority:
        params.append(("after", f"priority:{after_priority}"))
    if status:
        params.append(("status", status))
    if ptype:
        params.append(("type", ptype))
    params.append(("num", str(num)))
    if page:
        params.append(("page", str(page)))
    inner = "&".join(f"{k}={urllib.parse.quote_plus(v, safe=':()')}" for k, v in params)
    url = f"{BASE}/xhr/query?url={urllib.parse.quote(inner, safe='')}&exp="

    key = hashlib.sha1(url.encode()).hexdigest()[:20]
    path = _cache_path("search", key, ".json")
    if path.exists():
        return json.loads(path.read_text("utf-8"))

    data = _get(url).json()
    res = data.get("results", {})
    out = {"total": res.get("total_num_results", 0), "results": []}
    for cluster in res.get("cluster", []):
        for r in cluster.get("result", []):
            p = r.get("patent", {})
            out["results"].append({
                "pub": p.get("publication_number"),
                "title": _strip_html(p.get("title", "")),
                "snippet": _strip_html(p.get("snippet", "")),
                "priority_date": p.get("priority_date"),
                "filing_date": p.get("filing_date"),
                "grant_date": p.get("grant_date"),
                "assignee": p.get("assignee", ""),
            })
    path.write_text(json.dumps(out), "utf-8")
    return out


def _strip_html(s: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def patent_url(pub: str) -> str:
    return f"{BASE}/patent/{pub}/en"
