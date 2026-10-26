"""Graveyard Shift: Streamlit entry point. Run with `streamlit run app.py`."""

import sys
import types
from pathlib import Path

import streamlit as st

_ROOT = Path(__file__).resolve().parent
_PACKAGES = ("graveyard", "ui")


def _drop_stale_modules():
    """Streamlit Cloud pulls new commits into a running app but keeps modules it already
    imported, so new code can call functions the old modules don't have. When any of our
    source files changed since the last run (or on the first run of this check), drop our
    modules so the imports below load the current code."""
    snap = sys.modules.setdefault("_graveyard_shift_snapshot", types.ModuleType("_graveyard_shift_snapshot"))
    current = {str(p): p.stat().st_mtime for pkg in _PACKAGES for p in (_ROOT / pkg).rglob("*.py")}
    if getattr(snap, "mtimes", None) != current:
        for name in [n for n in sys.modules if n.split(".")[0] in _PACKAGES]:
            del sys.modules[name]
        snap.mtimes = current


_drop_stale_modules()

from graveyard import config  # noqa: E402
from ui import about, common, dashboard, marketplace, patent, prior_art, proof, style  # noqa: E402

st.set_page_config(page_title=config.PRODUCT_NAME, page_icon=":material/deceased:", layout="wide")
style.inject()

common.PAGES.clear()  # rebuilt every run, so the menu order always matches this list
common.PAGES.update(
    dashboard=st.Page(dashboard.page, title="Dashboard", icon=":material/dashboard:", url_path="dashboard", default=True),
    market=st.Page(marketplace.page, title="Marketplace", icon=":material/search:", url_path="market"),
    patent=st.Page(patent.page, title="Patent report", icon=":material/description:", url_path="patent"),
    prior=st.Page(prior_art.page, title="Prior-art check", icon=":material/travel_explore:", url_path="prior-art"),
    proof=st.Page(proof.page, title="Proof", icon=":material/verified:", url_path="proof"),
    about=st.Page(about.page, title="How it works", icon=":material/account_tree:", url_path="how"),
)

nav = st.navigation(list(common.PAGES.values()))
with st.sidebar:
    st.markdown(f"### {config.PRODUCT_NAME}")
    st.caption("Research and triage only, not legal advice. Don't type unprotected ideas.")
    common.passcode_box()
nav.run()
