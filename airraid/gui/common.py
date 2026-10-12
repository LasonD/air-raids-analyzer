"""Shared GUI state: the replay clock, settings, stage runs and caches, and chart helpers."""
from __future__ import annotations

import json
import time
from dataclasses import astuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from airraid import paths
from airraid import pipeline as P
from airraid.config import Config
from airraid.features import Inputs
from airraid.models import Boosting
from airraid.regions import BY_CODE, EXCLUDED
from airraid.sources import registry

RESULTS = paths.RESULTS
GEOJSON = paths.ASSETS / "ukraine_adm1.geojson"
KYIV = "Europe/Kyiv"
CFG = Config()
FIRST, LAST = CFG.val_start, CFG.data_end  # the replay clock moves inside the validation and test weeks
# Read-only charts: no toolbar, no zoom (a zoom without its reset button cannot be undone); hover stays.
NO_TOOLBAR = {"displayModeBar": False, "scrollZoom": False, "doubleClick": False}
CHANNELS = {"povitryanatrivogaaa": "alert-map channel", "kpszsu": "Air Force channel"}
SOURCE_NAMES = {"etryvoga": "Alert history", "kpszsu": "Air Force", "povitryanatrivogaaa": "Alert map"}

# Reference palette (dataviz skill). Red is reserved for "an alert happened".
BLUE, AQUA, GREY, ALERT_RED, AMBER = "#2a78d6", "#1baf7a", "#8a8985", "#d03b3b", "#c98a12"
KIND_COLORS = {"drone": BLUE, "missile": "#7a52c7", "aviation": AMBER, "explosion": "#d4498f", "clear": AQUA}
THEMES = {  # probability ramp runs from the page surface towards high contrast in both themes
    "light": dict(ramp=["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
                  surface="#ffffff", excluded="#e3e2de"),
    "dark": dict(ramp=["#1b2a40", "#1c3f6e", "#1c5cab", "#2a78d6", "#5598e7", "#9ec5f4", "#cde2fb"],
                 surface="#0e1117", excluded="#2a2b31"),
}

# key: (title, one-line tooltip). Order = the pipeline.
STAGES = {
    "sources": ("Sources", "Load the alert history and two Telegram channels; see what has arrived by 'now'."),
    "parsing": ("Parsing", "Turn free-text posts into threat events: kind and regions."),
    "format": ("Format", "One internal format for every source, lined up hour by hour."),
    "patterns": ("Patterns", "What the alert history shows, and what it means for the model."),
    "model": ("Model", "Retrain weekly on past data only; score the latest weeks."),
    "forecast": ("Forecast", "The forecast made at 'now': 24 regions × 24 hours ahead."),
    "result": ("Result", "How good it is, what Telegram adds, what acting on it would give."),
}
CHEAP = {"sources", "parsing", "format", "patterns", "result"}  # follow the clock by themselves once run


# ---------------------------------------------------------------- state

def now() -> pd.Timestamp:
    return st.session_state.setdefault("now", LAST)


def set_now(t: pd.Timestamp) -> None:
    """Only the non-widget key; the clock widgets are synced at the start of the next run."""
    st.session_state["now"] = min(max(pd.Timestamp(t).floor("h"), FIRST), LAST)


def select(stage: str) -> None:
    st.session_state["stage"] = stage


def selected() -> str:
    return st.session_state.setdefault("stage", "sources")


DEFAULTS = {"ch_povitryanatrivogaaa": True, "ch_kpszsu": False, "train_days": 182, "max_alert_hours": 12,
            "exclude_edited": True, "n_weeks": 4}


def settings() -> P.Settings:
    ss = st.session_state
    return P.Settings(channels=tuple(c for c in P.SIGNALS if ss.get(f"ch_{c}", DEFAULTS[f"ch_{c}"])),
                      train_days=ss.get("train_days", 182), exclude_edited=ss.get("exclude_edited", True),
                      max_alert_hours=float(ss.get("max_alert_hours", 12)))


def signature(stage: str) -> tuple:
    """What a stage's output depends on; plain values, so a code reload does not invalidate stored runs."""
    s, t = astuple(settings()), now()
    return {"sources": (), "parsing": (), "format": (t, s[3]), "patterns": (t, s[3]),
            "model": (t, s, st.session_state.get("n_weeks", 4)), "forecast": (t, s), "result": ()}[stage]


def runs() -> dict:
    return st.session_state.setdefault("runs", {})


def record(stage: str, seconds: float, out=None, note: str = "") -> None:
    runs()[stage] = {"sig": signature(stage), "seconds": seconds, "out": out, "note": note}


def status(stage: str) -> str:
    r = runs().get(stage)
    if r is None:
        return "not run"
    if r["sig"] == signature(stage) or stage in CHEAP:
        return "done"
    return "out of date"


ICON = {"not run": "○", "done": "✓", "out of date": "⚠", "running": "⏳"}


# ---------------------------------------------------------------- cached data and models

@st.cache_resource(show_spinner=False)
def source(name: str):
    return registry()[name].load()


def inputs() -> Inputs:
    return Inputs(source("etryvoga"), [source(s) for s in P.SIGNALS])


@st.cache_resource(show_spinner=False)
def store(name: str) -> dict:
    """Server-wide dicts for parsed posts and trained models; unlike module globals they survive code reloads."""
    return {}


def classified(channel: str) -> pd.DataFrame | None:
    """Parsed posts of a channel (None = texts not downloaded or not parsed yet)."""
    return store("posts").get(channel)


def set_classified(channel: str, posts: pd.DataFrame | None) -> None:
    store("posts")[channel] = posts


@st.cache_resource(show_spinner=False, max_entries=3)
def feature_set(t: pd.Timestamp, train_days: int, exclude_edited: bool, max_alert_hours: float):
    s = P.Settings(train_days=train_days, exclude_edited=exclude_edited, max_alert_hours=max_alert_hours)
    return P.features(inputs(), t, s)


def features_now(s: P.Settings):
    return feature_set(now(), s.train_days, s.exclude_edited, s.max_alert_hours)


def model_key(s: P.Settings, channels: tuple[str, ...], week: pd.Timestamp) -> tuple:
    return week, channels, s.train_days, s.exclude_edited and bool(channels), s.max_alert_hours


def has_models(s: P.Settings, week: pd.Timestamp) -> bool:
    return all(model_key(s, c, week) in store("models") for c in {(), s.channels})


def models(fs, s: P.Settings, week: pd.Timestamp, log=None) -> tuple[Boosting | None, Boosting]:
    """(Telegram model for 1-3 h, alert-history model), trained once per week; a model never depends on the clock."""
    out, cache = {}, store("models")
    for channels in sorted({(), s.channels}, key=len, reverse=True):
        key = model_key(s, channels, week)
        if key not in cache:
            if log:
                log(f"training {model_name(channels)} for the week of {kyiv(week, '%d %b')}…")
            t0 = time.time()
            cache[key] = P.train(fs, s, channels, week)
            if log:
                log(f"trained {model_name(channels)} for the week of {kyiv(week, '%d %b')} ({time.time() - t0:.0f} s)")
        out[channels] = cache[key]
    return (out[s.channels] if s.channels else None), out[()]


def model_name(channels: tuple[str, ...]) -> str:
    return "alert history only" if not channels else "+ " + " & ".join(CHANNELS[c] for c in channels)


@st.cache_data(show_spinner=False)
def reference(stamp: tuple) -> dict:
    """The committed run (results/), the fixed reference everything else is compared with."""
    pred = pd.read_parquet(RESULTS / "predictions.parquet")
    return {
        "pred": pred, "test": pred[pred["period"] == "test"],
        "unc": pd.read_csv(RESULTS / "uncertainty.csv", dtype={"h": str}),
        "by_region": pd.read_csv(RESULTS / "metrics_by_region.csv"),
        "agreement": pd.read_csv(RESULTS / "alert_source_agreement.csv"),
    }


def ref() -> dict:
    return reference(tuple(f.stat().st_mtime for f in sorted(RESULTS.glob("*"))))


@st.cache_data(show_spinner=False)
def geo() -> dict:
    return rewind_for_plotly(json.loads(GEOJSON.read_text(encoding="utf-8")))


def ci(unc, metric, period, subset, h):
    r = unc[(unc["metric"] == metric) & (unc["period"] == period) & (unc["subset"] == subset) & (unc["h"] == str(h))]
    return float(r["point"].iat[0]), float(r["lo"].iat[0]), float(r["hi"].iat[0])


def skill(y, p, clim) -> float:
    """% better than the usual daily rhythm (Brier skill score)."""
    ref_err = np.mean((clim - y) ** 2)
    return float(1 - np.mean((p - y) ** 2) / ref_err) if ref_err > 0 else float("nan")


# ---------------------------------------------------------------- formatting and charts

def kyiv(ts: pd.Timestamp, fmt="%a %d %b %H:%M") -> str:
    return ts.tz_convert(KYIV).strftime(fmt)


def hour_span(start: pd.Timestamp) -> str:
    a = start.tz_convert(KYIV)
    return f"{a:%H:%M}–{a + pd.Timedelta(hours=1):%H:%M}"


def pct(x, digits=1) -> str:
    return f"{x * 100:.{digits}f}%"


def theme() -> dict:
    t = getattr(st.context, "theme", None)
    return THEMES["dark" if t is not None and t.type == "dark" else "light"]


def ramp() -> list:
    r = theme()["ramp"]
    return [[i / (len(r) - 1), c] for i, c in enumerate(r)]


_KEYS = {"n": 0}


def show(fig, height=None):
    """Plotly chart without toolbar; a fresh key each call so live updates can redraw the same slot."""
    _KEYS["n"] += 1
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", dragmode=False)
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, use_container_width=True, config=NO_TOOLBAR, key=f"fig{_KEYS['n']}")


def small(fig, height=260, title=None):
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=30 if title else 10, b=10),
                      title=dict(text=title, font=dict(size=14), x=0, xanchor="left") if title else None)
    return fig


def local(x):
    """Kyiv wall-clock time without zone, for Plotly (which does not handle UTC offsets in its date axes)."""
    if isinstance(x, (pd.Timestamp, pd.DatetimeIndex)):
        return x.tz_convert(KYIV).tz_localize(None)
    return x.dt.tz_convert(KYIV).dt.tz_localize(None)


def now_line(fig, t: pd.Timestamp, **kw):
    """Vertical line at the replay moment; everything right of it is not known yet."""
    x = local(t)
    fig.add_vline(x=x, line=dict(color=ALERT_RED, width=1.5, dash="dot"), **kw)
    fig.add_annotation(x=x, y=1, yref="paper", text="now", showarrow=False, xanchor="left", yanchor="bottom",
                       font=dict(color=ALERT_RED, size=11), **kw)


def rewind_for_plotly(geo: dict) -> dict:
    """Plotly (d3-geo) wants clockwise outer rings, GeoJSON (RFC 7946) uses counter-clockwise ones;
    with the wrong winding every region is drawn as 'the whole globe minus the region'."""
    def signed_area(ring):
        return sum(x0 * y1 - x1 * y0 for (x0, y0, *_), (x1, y1, *_) in zip(ring, ring[1:])) / 2

    for feature in geo["features"]:
        g = feature["geometry"]
        polygons = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for polygon in polygons:
            for i, ring in enumerate(polygon):
                if (signed_area(ring) < 0) != (i == 0):  # outer ring clockwise, holes counter-clockwise
                    ring.reverse()
    return geo


def ukraine_map(codes, probs, actual, value_label, height=440):
    th = theme()
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geo(), featureidkey="properties.shapeISO", locations=list(EXCLUDED), z=[0] * len(EXCLUDED),
        colorscale=[[0, th["excluded"]], [1, th["excluded"]]], showscale=False,
        marker_line_color=th["surface"], marker_line_width=1,
        hovertemplate="%{location}: not forecast (no usable alert data)<extra></extra>"))
    names = [BY_CODE[c].name for c in codes]
    outcome = [""] * len(codes) if actual is None else [" · alert happened" if a else " · no alert" for a in actual]
    fig.add_trace(go.Choropleth(
        geojson=geo(), featureidkey="properties.shapeISO", locations=codes, z=probs, zmin=0, zmax=1,
        colorscale=ramp(), marker_line_color=th["surface"], marker_line_width=1,
        customdata=np.array([names, outcome]).T,
        colorbar=dict(title=value_label, tickformat=".0%", orientation="h", x=0.5, y=-0.02, len=0.5, thickness=10),
        hovertemplate="%{customdata[0]}: %{z:.0%}%{customdata[1]}<extra></extra>"))
    if actual is not None and np.nansum(actual) > 0:
        hit = [c for c, a in zip(codes, actual) if a == 1]
        for color, width in ((th["surface"], 6), (ALERT_RED, 2.5)):  # surface halo keeps shared borders readable
            fig.add_trace(go.Choropleth(
                geojson=geo(), featureidkey="properties.shapeISO", locations=hit, z=[1] * len(hit),
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
                marker_line_color=color, marker_line_width=width, hoverinfo="skip"))
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="rgba(0,0,0,0)")
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=40))
    return fig


def hourly_chart(starts, values, rhythm, actual, mark=None, height=240):
    """Forecast per hour (line) vs the usual daily rhythm (dashed); a red strip marks hours with an alert."""
    mid = local(starts + pd.Timedelta(minutes=30))
    top = max(0.6, float(np.nanmax(values)) + 0.1)
    fig = go.Figure()
    if actual is not None:
        fig.add_trace(go.Bar(x=mid, y=np.where(actual == 1, top * 0.06, 0), width=3_600_000, name="alert happened",
                             marker_color=ALERT_RED, hovertemplate="%{x|%a %d %b %H:00}: alert<extra></extra>"))
    fig.add_trace(go.Scatter(x=mid, y=rhythm, name="usual daily rhythm", mode="lines",
                             line=dict(color=GREY, width=1.5, dash="dash"), hovertemplate="rhythm %{y:.0%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=mid, y=values, name="forecast", mode="lines", line=dict(color=BLUE, width=2.5),
                             hovertemplate="forecast %{y:.0%}<extra></extra>"))
    if mark is not None:
        fig.add_vrect(x0=local(mark), x1=local(mark + pd.Timedelta(hours=1)), fillcolor=BLUE, opacity=0.12, line_width=0)
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10), bargap=0, hovermode="x unified",
                      yaxis=dict(tickformat=".0%", range=[0, top]), legend=dict(orientation="h", y=-0.25))
    return fig
