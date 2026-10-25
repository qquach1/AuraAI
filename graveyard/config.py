"""Paths, model choice and environment flags shared by every module."""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# Nearest .env at or above the repo root (so a key in the main checkout also reaches worktrees)
for _d in [ROOT, *ROOT.parents]:
    if (_d / ".env").exists():
        load_dotenv(_d / ".env", encoding="utf-8-sig")  # tolerate the BOM Notepad/PowerShell can add
        break


def _streamlit_secret(name: str) -> str | None:
    """Read a key from Streamlit secrets (how Streamlit Community Cloud passes them)."""
    try:
        import streamlit as st
        value = st.secrets.get(name)
        return str(value) if value else None
    except Exception:  # no secrets file, or not running under Streamlit
        return None


# Hosted deploys keep secrets in Streamlit's secrets store rather than a .env file
for _name in ("ANTHROPIC_API_KEY", "GS_LIVE_CODE"):
    if not os.getenv(_name) and (_v := _streamlit_secret(_name)):
        os.environ[_name] = _v

PRODUCT_NAME = "Graveyard Shift"
TAGLINE = "Find the dead patents worth building on, and what still stands in the way."

DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("GS_DB", DATA_DIR / "graveyard.db"))
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = DATA_DIR / "reports"
BENCHMARK_DIR = DATA_DIR / "benchmark"
CHECKLIST_PATH = DATA_DIR / "blocker_checklist.json"

MODEL = os.getenv("GS_MODEL", "claude-opus-5-5")
OFFLINE = os.getenv("GS_OFFLINE", "") == "1"
# Market agent web search for current products and companies (adds ~30s and a few cents per report)
WEB_EVIDENCE = os.getenv("GS_WEB", "1") == "1"
# Public deploys: when set, live Claude runs need this team passcode. Saved reports stay open to all.
LIVE_CODE = os.getenv("GS_LIVE_CODE", "")
MAX_LIVE_RUNS = int(os.getenv("GS_MAX_LIVE_RUNS", "15"))  # per browser session, as a spending backstop

# All "as of" logic (term estimates, revival window, recent activity) keys off this date
# so a demo run gives the same answers every time.
AS_OF = date.fromisoformat(os.getenv("GS_AS_OF", "2026-10-25"))
# "Recent" citing filings, by priority date. Applications publish ~18 months after filing,
# so a 7-year priority window shows roughly the last 5 years of visible activity.
RECENT_YEARS = 7
RECENT_SINCE = AS_OF.year - RECENT_YEARS

DISCLAIMER = (
    "Research and triage only, not legal advice. This report is not a patentability, "
    "validity or freedom-to-operate opinion. Patent status shown here comes from public "
    "records that can lag or be wrong. An expired patent is not the same as free to use: "
    "follow-on patents, regulatory exclusivity, trade secrets and standards can still block "
    "a product. Confirm with a registered patent attorney before acting."
)

DISCLOSURE_WARNING = (
    "Anything you type here is sent to outside services (such as Anthropic's Claude API) and "
    "should be treated as publicly disclosed. Public disclosure can bar you from patenting an "
    "idea later. Only enter public patents or ideas that are already protected."
)


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY")) and not OFFLINE
