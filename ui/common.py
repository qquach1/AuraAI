"""Shared UI helpers: database handle, badges, guardrail notices."""

import streamlit as st

from graveyard import config, db

STATUS_LABEL = {
    "lapsed_fees": "Lapsed: unpaid fees",
    "expired_term": "Expired: full term",
    "in_force": "Still in force",
    "expired_other": "Expired (other)",
    "unknown": "Status unclear",
}
STATUS_COLOR = {"lapsed_fees": "orange", "expired_term": "gray", "in_force": "red",
                "expired_other": "gray", "unknown": "gray"}
CONF_COLOR = {"high": "green", "medium": "orange", "low": "red"}
SEV_COLOR = {"high": "red", "medium": "orange", "low": "gray"}

PAGES: dict = {}  # filled by app.py so pages can switch to each other


@st.cache_resource
def con():
    return db.connect()


def badge(text: str, color: str = "blue") -> str:
    return f":{color}-background[{text}]"


def status_badge(status: str) -> str:
    return badge(STATUS_LABEL.get(status, status), STATUS_COLOR.get(status, "gray"))


def score_color(score: int) -> str:
    return "green" if score >= 60 else ("orange" if score >= 40 else "red")


def open_patent(pub: str):
    st.session_state["pub"] = pub
    st.query_params["pub"] = pub
    st.switch_page(PAGES["patent"])


def legal_notice():
    st.info(f"**Research, not legal advice.** {config.DISCLAIMER}", icon=":material/gavel:")


def disclosure_notice():
    st.warning(f"**Anything you type counts as disclosed.** {config.DISCLOSURE_WARNING}", icon=":material/visibility:")


def mode_caption():
    if config.llm_available():
        st.caption(f"Agents run on `{config.MODEL}`.")
    else:
        st.caption("No Anthropic API key found: agents use rule-based fallbacks and cached reports.")
