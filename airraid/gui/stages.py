"""What each stage's Run button does. Rendering lives in the page modules."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from airraid import pipeline as P
from airraid.gui import common as C
from airraid.sources import registry


def run_sources(log=print) -> None:
    t0 = time.time()
    C.inputs()
    C.record("sources", time.time() - t0)
    log(f"sources loaded ({time.time() - t0:.1f} s)")


def run_parsing(log=print) -> None:
    t0 = time.time()
    for ch in P.SIGNALS:
        C.classified(ch)
    C.record("parsing", time.time() - t0)
    log(f"posts parsed ({time.time() - t0:.1f} s)")


@st.cache_data(show_spinner=False, max_entries=8)
def hourly(t: pd.Timestamp, max_alert_hours: float) -> pd.DataFrame:
    return P.hourly_history(C.inputs().alerts, t, max_alert_hours)


def run_format(log=print) -> None:
    t0 = time.time()
    hourly(C.now(), C.settings().max_alert_hours)
    C.record("format", time.time() - t0)
    log(f"common format and hourly table ({time.time() - t0:.1f} s)")


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


def run_patterns(log=print) -> None:
    t0 = time.time()
    patterns(C.now(), C.settings().max_alert_hours)
    C.record("patterns", time.time() - t0)
    log(f"patterns ({time.time() - t0:.1f} s)")


def run_model(log=print, progress=None) -> None:
    t0 = time.time()
    s, t = C.settings(), C.now()
    fs = C.features_now(s)
    blocks = P.scoring_weeks(s.config(), t, st.session_state.get("n_weeks", 4))
    out = []
    for i, (w, end) in enumerate(blocks):
        short, long = C.models(fs, s, w, log)
        out.append(P.predict(fs, s, short, long, w, end).dropna(subset=["y"]))
        if progress:
            progress((i + 1) / len(blocks), f"week of {C.kyiv(w, '%d %b')} scored")
    pred = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    C.record("model", time.time() - t0, out=pred)
    log(f"model & test: {len(blocks)} weeks ({time.time() - t0:.0f} s)")


def run_forecast(log=print) -> None:
    t0 = time.time()
    s, t = C.settings(), C.now()
    fs = C.features_now(s)
    week = P.week_of(s.config(), t)
    short, long = C.models(fs, s, week, log)
    fc = P.predict(fs, s, short, long, t, t + P.HOUR)
    so_far = P.predict(fs, s, short, long, week, t - pd.Timedelta(hours=23)).dropna(subset=["y"]) \
        if t - pd.Timedelta(hours=23) > week else pd.DataFrame()
    C.record("forecast", time.time() - t0, out={"fc": fc, "so_far": so_far, "week": week})
    log(f"forecast made at {C.kyiv(t)} ({time.time() - t0:.0f} s)")


def run_all(log=print) -> None:
    run_sources(log)
    run_parsing(log)
    run_format(log)
    run_patterns(log)
    run_model(log)
    run_forecast(log)


def fetch_live() -> None:
    """The newest page of each channel, straight from Telegram."""
    posts = {ch: registry()[ch].latest_posts() for ch in P.SIGNALS}
    st.session_state["live"] = {"at": pd.Timestamp.now(tz="UTC"), "posts": posts}
