"""Graveyard Shift: Streamlit entry point. Run with `streamlit run app.py`."""

import streamlit as st

from graveyard import config
from ui import about, common, marketplace, patent, prior_art, proof

st.set_page_config(page_title=config.PRODUCT_NAME, page_icon=":material/deceased:", layout="wide")

common.PAGES.update(
    market=st.Page(marketplace.page, title="Marketplace", icon=":material/search:", url_path="market", default=True),
    patent=st.Page(patent.page, title="Patent report", icon=":material/description:", url_path="patent"),
    prior=st.Page(prior_art.page, title="Prior-art check", icon=":material/travel_explore:", url_path="prior-art"),
    proof=st.Page(proof.page, title="Proof", icon=":material/verified:", url_path="proof"),
    about=st.Page(about.page, title="How it works", icon=":material/account_tree:", url_path="how"),
)

nav = st.navigation(list(common.PAGES.values()))
with st.sidebar:
    st.markdown(f"### {config.PRODUCT_NAME}")
    st.caption("Research and triage only, not legal advice. Don't type unprotected ideas.")
nav.run()
