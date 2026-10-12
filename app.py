"""Streamlit GUI: python -m airraid gui

The pipeline as one screen: a replay clock on top, the stages as clickable nodes, and the selected stage
below. Running a stage draws its view as it computes; every stage sees only data published before "now".
"""
from __future__ import annotations

import streamlit as st

from airraid.gui import common as C
from airraid.gui import views as V

st.set_page_config(page_title="Air raid alert forecast", layout="wide", initial_sidebar_state="collapsed")
st.html(V.CSS)

top = V.top_bar()
# "Run all" is a queue worked off one stage per script run, so each stage starts on a clean screen.
if top["run_all"]:
    V.enqueue(V.ORDER[:-1], then="result")
queue = st.session_state.get("queue") or []
if queue:
    C.select(queue[0])
elif top["play"]:
    C.select("forecast")
bar = V.strip()
panel = st.container(key="panel")

if queue:
    total = st.session_state.get("queue_total", len(queue))
    done = total - len(queue)
    bar.progress(done / total, f"Running {C.STAGES[queue[0]][0]} ({done + 1} of {total})")
    with panel:
        V.render(queue[0], run=True)
    st.session_state["queue"] = queue[1:]
    if not queue[1:]:
        C.select(st.session_state.get("queue_then", "result"))
    st.rerun()
elif top["play"]:
    with panel:
        V.render("forecast", play=True)
    st.rerun()
else:
    with panel:
        clicked = V.render(C.selected())
    if clicked:
        st.rerun()  # redraw the strip and buttons with the new status
