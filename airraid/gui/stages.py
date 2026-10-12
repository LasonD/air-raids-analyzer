"""Cached computations behind the stage views (no rendering here)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from airraid import pipeline as P
from airraid.gui import common as C
from airraid.sources import registry


@st.cache_data(show_spinner=False, max_entries=8)
def hourly(t: pd.Timestamp, max_alert_hours: float) -> pd.DataFrame:
    return P.hourly_history(C.inputs().alerts, t, max_alert_hours)


@st.cache_data(show_spinner=False, max_entries=8)
def patterns(t: pd.Timestamp, max_alert_hours: float) -> dict:
    H = hourly(t, max_alert_hours)
    recent = H[H.index >= t - pd.Timedelta(days=182)]
    month = H.mean(axis=1).resample("MS").agg(["mean", "size"])
    month = month[month["size"] == month.index.days_in_month * 24]  # whole months only
    local = recent.copy()
    local.index = recent.index.tz_convert(C.KYIV)
    dur = P.durations(C.inputs().alerts, t)
    nb, other = P.neighbour_correlation(recent)
    return {
        "monthly": month["mean"],
        "rhythm": local.groupby(local.index.hour).mean().T,
        "weekday": local.mean(axis=1).groupby(local.index.dayofweek).mean(),
        "persistence": P.persistence(recent),
        "durations": dur[dur["start_utc"] >= t - pd.Timedelta(days=182)]["hours"],
        "together": recent.dropna().sum(axis=1).astype(int).value_counts().sort_index() / len(recent.dropna()),
        "nb_corr": nb, "other_corr": other,
    }


@st.cache_data(show_spinner=False)
def daily_counts() -> pd.DataFrame:
    inp = C.inputs()
    a = inp.alerts.frame
    out = {"etryvoga": a.groupby(a["start_utc"].dt.floor("D")).size()}
    for s in inp.signals:
        f = s.frame.drop_duplicates(["ref", "published_at_utc"])
        out[s.name] = f.groupby(f["published_at_utc"].dt.floor("D")).size()
    df = pd.DataFrame(out).fillna(0)
    return df[df.index >= pd.Timestamp("2026-01-01", tz="UTC")]


def fetch_live() -> None:
    """The newest page of each channel, straight from Telegram."""
    posts = {ch: registry()[ch].latest_posts() for ch in P.SIGNALS}
    st.session_state["live"] = {"at": pd.Timestamp.now(tz="UTC"), "posts": posts}
