"""Streamlit GUI: python -m airraid gui

The pipeline as an app: one page per stage, from the raw sources to the forecast and its scores. A replay
clock in the sidebar sets the moment the app stands at; every stage sees only data published before it.
"""
from __future__ import annotations

import streamlit as st

from airraid.gui import common as C
from airraid.gui import data_pages as D
from airraid.gui import model_pages as M

st.set_page_config(page_title="Air raid alert forecast", layout="wide")

pages = {
    "overview": st.Page(D.overview, title="Overview", url_path="overview", default=True),
    "sources": st.Page(D.sources, title="1 · Sources", url_path="sources"),
    "parsing": st.Page(D.parsing, title="2 · Parsing", url_path="parsing"),
    "format": st.Page(D.common_format, title="3 · Common format", url_path="format"),
    "patterns": st.Page(D.patterns, title="4 · Patterns", url_path="patterns"),
    "model": st.Page(M.model, title="5 · Model & test", url_path="model"),
    "forecast": st.Page(M.forecast, title="6 · Forecast", url_path="forecast"),
    "result": st.Page(M.result, title="7 · Result", url_path="result"),
}
C.PAGES.update(pages)
nav = st.navigation(list(pages.values()), position="top")
C.sidebar()
nav.run()
C.sidebar_stages()  # after the page, so a Run on it shows up at once
