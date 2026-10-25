"""Shared UI helpers: database handle, badges, guardrail notices."""

import hmac

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


def live_allowed() -> bool:
    """Whether this browser session may make live Claude calls (costs money on a public deploy)."""
    if not config.llm_available():
        return False
    if config.LIVE_CODE and not st.session_state.get("live_ok"):
        return False
    return st.session_state.get("live_runs", 0) < config.MAX_LIVE_RUNS


def count_live_run():
    st.session_state["live_runs"] = st.session_state.get("live_runs", 0) + 1


def passcode_box():
    """Sidebar unlock for live agent runs, shown only when the deploy sets GS_LIVE_CODE."""
    if not (config.LIVE_CODE and config.llm_available()):
        return
    if st.session_state.get("live_ok"):
        left = config.MAX_LIVE_RUNS - st.session_state.get("live_runs", 0)
        st.caption(f":material/lock_open: Live agent runs unlocked ({max(0, left)} left this session).")
        return
    code = st.text_input("Team passcode for live agent runs", type="password",
                         help="Saved reports are open to everyone. Running Claude live costs money, so it needs the passcode.")
    if code:
        if hmac.compare_digest(code.strip(), config.LIVE_CODE):
            st.session_state["live_ok"] = True
            st.rerun()
        else:
            st.error("That passcode didn't match.")


def mode_caption():
    if not config.llm_available():
        st.caption("No Anthropic API key found: agents use rule-based fallbacks and saved reports.")
    elif config.LIVE_CODE and not st.session_state.get("live_ok"):
        st.caption("Live Claude runs are locked: enter the team passcode in the sidebar. Saved reports are open to everyone, "
                   "and other patents get a rule-based report.")
    elif not live_allowed():
        st.caption(f"This session has used its {config.MAX_LIVE_RUNS} live runs; agents fall back to rule-based output.")
    else:
        st.caption(f"Agents run on `{config.MODEL}`.")
