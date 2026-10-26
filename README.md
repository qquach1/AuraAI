# Graveyard Shift

An AI-agent marketplace for lapsed and expired US patents. A founder searches the patent
graveyard, opens a patent card, and gets an agent-written triage report: a revival score
with a confidence level, the evidence behind it, what could still block use, and the one
assumption to test first. Built for the AI Heist hackathon (Agentic AI vault, problem 1).

Research and triage only, never a legal opinion. Expired is not the same as free to use.

## Run it

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
powershell -ExecutionPolicy Bypass -File scripts/set_api_key.ps1   # or copy .env.example to .env
.venv/Scripts/python -m streamlit run app.py
```

### Deploy (Streamlit Community Cloud)

1. At [share.streamlit.io](https://share.streamlit.io), create an app from `qquach1/AuraAI`, branch `main`, file `app.py`.
2. Under Advanced settings pick Python 3.12 and paste the secrets:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   GS_LIVE_CODE = "a passcode for teammates"
   ```
3. Deploy, then share the link and, separately, the passcode.

Anyone with the link can browse the marketplace and read the saved Claude reports. Live Claude
runs (re-running agents, Scout's search expansion, live prior-art checks) need the passcode,
and each browser session is capped at 15 (`GS_MAX_LIVE_RUNS`). Without the passcode, patents
with no saved report get a free rule-based report.

**Never commit `.env`.** This repo is public; a key pushed here is exposed at once and must be
revoked. `.env` is in `.gitignore`; `scripts/set_api_key.ps1` writes it with the key hidden.

The repo ships with the sample database (`data/graveyard.db`), cached reports
(`data/reports/`) and benchmark results (`data/benchmark/`), so the demo runs offline.
Without an API key the agents fall back to rule-based output; cached reports still show.

Rebuild the data (slow, polite crawl; resumable):

```bash
GS_SOURCE=wayback .venv/Scripts/python scripts/build_sample.py --per-class 40
.venv/Scripts/python scripts/run_benchmark.py --targets 10
.venv/Scripts/python scripts/pregenerate_reports.py --top 3
```

## How it works

Six agents and one orchestrator (`graveyard/orchestrator.py`). Agents never call each
other; every finding is an evidence record in a shared store, and the report may only
make claims that cite one. Code computes every number; Claude reads and writes.

| Agent | File | Job | Claude? |
| --- | --- | --- | --- |
| Scout | `graveyard/agents/scout.py` | Candidates by class and keyword; similar dead patents | Expands plain words into patent vocabulary |
| Status | `graveyard/agents/status.py` | Expired at term, lapsed for fees, or in force; fee window; owner size; revival risk | No (records only) |
| Blocker | `graveyard/agents/blocker.py` | Live family, owner follow-ons, examiner-linked live patents, regulatory exclusivity, revival | Rates follow-on overlap |
| Market | `graveyard/agents/market.py` | Citation activity, citing companies, revival score + confidence | Interprets the evidence |
| Report | `graveyard/agents/report.py` | Triage report and the one assumption to test; verifier pass | Writes the report |
| Prior-art | `graveyard/agents/prior_art.py` | Earlier patents an examiner would cite (brief Q3) | Plans queries, reranks |

- Revival score: `graveyard/scoring.py`, a weighted sum of six named signals.
- Blocker checklist: `data/blocker_checklist.json` (Juan owns the wording).
- Status and citation metrics: `graveyard/derive.py`.
- Screens: `app.py` and `ui/` (Dashboard, Marketplace, Patent report, Prior-art check, Proof, How it works).

**Dashboard** (`ui/dashboard.py`), the home page, has three tabs:

- *Overview*: counts, where dead patents are still being built on, top opportunities, latest deals. All computed from our data.
- *Simulation Lab* (`graveyard/agents/simulate.py`): a founder's idea run through Scout, Prior-art, a Market web search and Report, giving market opportunity, patent landscape, strategic pathways and the assumption to test. A saved example runs offline.
- *Deals & news* (`graveyard/agents/news.py`, `data/news.json`): recent M&A, licensing, litigation and regulatory events per field from Claude web search, each dated and linked to its source. Refresh with `scripts/refresh_news.py` (about $0.25 per field).

## Data

216 dead US patents across 38 CPC subclasses (78 lapsed for unpaid fees, 138 expired at full
term), sampled by walking the citation lists of well-known seed patents in ten fields, plus a
prior-art corpus of 31,950 US documents (those pages and everything they cite or are cited by).

Records are public Google Patents pages (bibliographic data, USPTO maintenance-fee legal
events, citations with examiner flags, family status). On Oct 25 Google Patents rate-limited
our network, so the sample was pulled from the Internet Archive's snapshots of the same pages
(`GS_SOURCE=wayback`); each record keeps its source and snapshot date. When an older snapshot
still says Active but the expected expiration date has passed, the status is marked as inferred.
All dates are evaluated as of 2026-10-25 (`GS_AS_OF`).

## Proof: prior-art benchmark (brief question 3)

On 10 recently granted public US patents, given only the title, abstract and first claim and
limited to earlier documents, the Prior-art agent put **21 of the examiner's 83 cited US
references in its top 10 (recall@10 25%)**, against 5 of 83 (6%) for a single keyword search
over the same pool, and found at least one on 7 of 10 targets (keyword search: 4). The pool is
36,004 US documents, including the targets' full citation tables mixed in as title-only rows
(a pooled benchmark, not a search of every US patent). Full method and caveats:
`data/benchmark/results.json`, the app's Proof page, and `scripts/run_benchmark.py`.

## Cost per report

Measured on `claude-opus-5-5`: about $0.24 and 70 seconds per full report, of which about $0.16
is the Market agent's web search for current products and companies (`GS_WEB=0` turns it off,
bringing a report to about $0.09). Every report's agent trace lists each Claude call with
tokens and cost.

## Guardrails

- "Research, not legal advice" notice on every report and in every export.
- A disclosure warning on every input: anything typed is sent to outside services.
- The verifier deletes report points with no evidence and rewrites legal-opinion wording.
- Every report runs the Blocker agent before anything is called usable.
- Tests use public patents only.
