"""Shared GUI state: the replay clock, settings, cached stage outputs, and chart helpers."""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from airraid import paths
from airraid import pipeline as P
from airraid.config import Config
from airraid.models import Boosting
from airraid.regions import BY_CODE, EXCLUDED
from airraid.sources import registry

RESULTS = paths.RESULTS
GEOJSON = paths.ASSETS / "ukraine_adm1.geojson"
KYIV = "Europe/Kyiv"
CFG = Config()
FIRST, LAST = CFG.val_start, CFG.data_end  # the replay clock moves inside the validation and test weeks
NO_TOOLBAR = {"displayModeBar": False}
CHANNELS = {"povitryanatrivogaaa": "alert-map channel", "kpszsu": "Air Force channel"}

# Reference palette (dataviz skill). Red is reserved for "an alert happened".
BLUE, AQUA, GREY, ALERT_RED, AMBER = "#2a78d6", "#1baf7a", "#8a8985", "#d03b3b", "#c98a12"
KIND_COLORS = {"drone": BLUE, "missile": "#7a52c7", "aviation": AMBER, "explosion": "#d4498f", "clear": AQUA}
THEMES = {  # probability ramp runs from the page surface towards high contrast in both themes
    "light": dict(ramp=["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
                  surface="#ffffff", excluded="#e3e2de"),
    "dark": dict(ramp=["#1b2a40", "#1c3f6e", "#1c5cab", "#2a78d6", "#5598e7", "#9ec5f4", "#cde2fb"],
                 surface="#0e1117", excluded="#2a2b31"),
}
PAGES: dict = {}  # filled by app.py, for links between pages

STAGES = {  # key: (number, title, what it does)
    "sources": ("1", "Sources", "Load the alert history and the two Telegram channels; see what has arrived by the replay moment."),
    "parsing": ("2", "Parsing", "Turn free-text Telegram posts into threat events: what kind, which regions."),
    "format": ("3", "Common format", "Check every source against one internal format and line them up hour by hour."),
    "patterns": ("4", "Patterns", "What the alert history itself shows, and what that means for the model."),
    "model": ("5", "Model & test", "Retrain weekly on past data only and score the forecasts of the latest weeks."),
    "forecast": ("6", "Forecast", "The forecast made at the replay moment, for every region and the next 24 hours."),
}


# ---------------------------------------------------------------- state

def now() -> pd.Timestamp:
    return st.session_state.setdefault("now", LAST)


def set_now(t: pd.Timestamp) -> None:
    t = min(max(pd.Timestamp(t).floor("h"), FIRST), LAST)
    st.session_state["now"] = t
    local = t.tz_convert(KYIV)
    st.session_state["clock_day"], st.session_state["clock_hour"] = local.date(), local.hour


def settings() -> P.Settings:
    ss = st.session_state
    return P.Settings(channels=tuple(c for c in P.SIGNALS if ss.get(f"ch_{c}", c == "povitryanatrivogaaa")),
                      train_days=ss.get("train_days", 182), exclude_edited=ss.get("exclude_edited", True),
                      max_alert_hours=float(ss.get("max_alert_hours", 12)))


def signature(stage: str) -> tuple:
    s, t = settings(), now()
    return {"sources": (), "parsing": (), "format": (t, s.max_alert_hours), "patterns": (t, s.max_alert_hours),
            "model": (t, s, st.session_state.get("n_weeks", 4)), "forecast": (t, s)}[stage]


def runs() -> dict:
    return st.session_state.setdefault("runs", {})


def record(stage: str, seconds: float, out=None) -> None:
    runs()[stage] = {"sig": signature(stage), "seconds": seconds, "out": out, "at": pd.Timestamp.now(tz=KYIV)}


def status(stage: str) -> str:
    r = runs().get(stage)
    if r is None:
        return "not run"
    return "done" if r["sig"] == signature(stage) else "out of date"


BADGE = {"not run": "○ not run yet", "done": "✓ up to date", "out of date": "⚠ inputs changed: run again"}
CHEAP = {"sources", "parsing", "format", "patterns"}  # recompute by themselves when their page opens


def shown_status(stage: str) -> str:
    """Status for overviews: a data stage that has run is never stale, it follows the clock when opened."""
    state = status(stage)
    return "done" if stage in CHEAP and state == "out of date" else state


def stage_header(stage: str, cheap: bool) -> bool:
    """Title, status and Run button. Returns True when the stage should compute now.

    Cheap stages, once run, follow the clock by themselves; model stages wait for a click.
    """
    num, title, what = STAGES[stage]
    st.title(f"{num} · {title}")
    st.markdown(what)
    state = status(stage)
    a, b = st.columns([1, 5], vertical_alignment="center")
    clicked = a.button("Run" if state == "not run" else "Run again", key=f"run_{stage}",
                       type="primary" if state != "done" else "secondary", use_container_width=True)
    r = runs().get(stage)
    took = f" · last run took {r['seconds']:.1f} s" if r else ""
    b.markdown(f"**{BADGE[state] if not (cheap and r) else BADGE['done']}**{took}")
    return clicked or (cheap and r is not None and state == "out of date")


DEFAULTS = {"ch_povitryanatrivogaaa": True, "ch_kpszsu": False, "train_days": 182, "max_alert_hours": 12,
            "exclude_edited": True, "n_weeks": 4}


def _clock_from_widgets():
    day, hour = st.session_state["clock_day"], st.session_state["clock_hour"]
    set_now(pd.Timestamp(day).replace(hour=hour).tz_localize(KYIV).tz_convert("UTC"))


def _step(hours: int):
    set_now(now() + pd.Timedelta(hours=hours))


def _reset_settings():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v


def sidebar():
    """The replay clock and the inputs: global state every stage reads."""
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)
    if "clock_day" not in st.session_state:
        set_now(now())
    sb = st.sidebar
    sb.markdown("### ⏱ Replay clock")
    sb.caption("The app sees only what was published before this moment.")
    c1, c2 = sb.columns([3, 2])
    c1.date_input("Day (Kyiv)", key="clock_day", min_value=FIRST.tz_convert(KYIV).date(),
                  max_value=LAST.tz_convert(KYIV).date(), on_change=_clock_from_widgets, format="DD.MM.YYYY")
    c2.selectbox("Hour", list(range(24)), key="clock_hour", format_func=lambda h: f"{h:02d}:00",
                 on_change=_clock_from_widgets)
    cols = sb.columns(4)
    for col, (label, hours) in zip(cols, (("−1 d", -24), ("−1 h", -1), ("+1 h", 1), ("+1 d", 24))):
        col.button(label, on_click=_step, args=(hours,), use_container_width=True, key=f"step_{hours}")
    sb.button("Go to the end of the data", on_click=set_now, args=(LAST,), use_container_width=True,
              disabled=now() == LAST)
    sb.markdown(f"**Now: {kyiv(now())}** (Kyiv)")
    sb.divider()
    sb.markdown("### Inputs")
    sb.caption("The alert history is always used; it is also what is forecast.")
    for ch, name in CHANNELS.items():
        sb.toggle(f"{name.capitalize()} (@{ch})", key=f"ch_{ch}")
    with sb.expander("Model settings"):
        st.select_slider("Training window (days)", [56, 91, 126, 182], key="train_days")
        st.select_slider("Cap alerts at (hours)", [6, 12, 24], key="max_alert_hours")
        st.checkbox("Leave out edited Telegram posts", key="exclude_edited")
        st.slider("Weeks to score (stage 5)", 1, 8, key="n_weeks")
        st.button("Reset to the committed settings", on_click=_reset_settings, use_container_width=True)


def sidebar_stages():
    sb = st.sidebar
    sb.divider()
    sb.markdown("### Stages")
    for key, (num, title, _) in STAGES.items():
        sb.caption(f"{num} · {title}: {BADGE[shown_status(key)]}")


# ---------------------------------------------------------------- cached stage outputs

@st.cache_resource(show_spinner=False)
def inputs():
    return P.load_sources()


@st.cache_resource(show_spinner=False)
def classified(channel: str) -> pd.DataFrame | None:
    src = registry()[channel]
    return src.classified_posts() if src.has_pages() else None


@st.cache_resource(show_spinner=False, max_entries=3)
def feature_set(t: pd.Timestamp, train_days: int, exclude_edited: bool, max_alert_hours: float):
    s = P.Settings(train_days=train_days, exclude_edited=exclude_edited, max_alert_hours=max_alert_hours)
    return P.features(inputs(), t, s)


def features_now(s: P.Settings):
    return feature_set(now(), s.train_days, s.exclude_edited, s.max_alert_hours)


_MODELS: dict[tuple, Boosting] = {}  # one per (week, inputs, settings); a model never depends on the clock


def model_key(s: P.Settings, channels: tuple[str, ...], week: pd.Timestamp) -> tuple:
    return week, channels, s.train_days, s.exclude_edited and bool(channels), s.max_alert_hours


def has_models(s: P.Settings, week: pd.Timestamp) -> bool:
    return all(model_key(s, c, week) in _MODELS for c in {(), s.channels})


def models(fs, s: P.Settings, week: pd.Timestamp, log=None) -> tuple[Boosting | None, Boosting]:
    """(Telegram model for 1-3 h, alert-history model), trained once per week and kept in memory."""
    out = {}
    for channels in {(), s.channels}:
        key = model_key(s, channels, week)
        if key not in _MODELS:
            t0 = time.time()
            _MODELS[key] = P.train(fs, s, channels, week)
            if log:
                log(f"week of {kyiv(week, '%d %b')}: trained {model_name(channels)} ({time.time() - t0:.0f} s)")
        out[channels] = _MODELS[key]
    return (out[s.channels] if s.channels else None), out[()]


def model_name(channels: tuple[str, ...]) -> str:
    return "alert history only" if not channels else "+ " + " & ".join(CHANNELS[c] for c in channels)


def main_model_name(s: P.Settings) -> str:
    if not s.channels:
        return "alert history only"
    return f"Telegram ({' & '.join(CHANNELS[c] for c in s.channels)}) for 1–3 h ahead, alert history only after"


@st.cache_data(show_spinner=False)
def reference(stamp: tuple) -> dict:
    """The committed run (results/), the fixed reference everything else is compared with."""
    pred = pd.read_parquet(RESULTS / "predictions.parquet")
    return {
        "pred": pred, "test": pred[pred["period"] == "test"],
        "unc": pd.read_csv(RESULTS / "uncertainty.csv", dtype={"h": str}),
        "health": {h["source"]: h for h in json.loads((RESULTS / "source_health.json").read_text())},
        "overall": pd.read_csv(RESULTS / "metrics_overall.csv"),
        "by_region": pd.read_csv(RESULTS / "metrics_by_region.csv"),
        "agreement": pd.read_csv(RESULTS / "alert_source_agreement.csv"),
        "run": json.loads((RESULTS / "run.json").read_text()),
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


def show(fig, key=None):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, config=NO_TOOLBAR, key=key)


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


def ukraine_map(codes, probs, actual, value_label):
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
    if actual is not None and actual.any():
        hit = [c for c, a in zip(codes, actual) if a == 1]
        for color, width in ((th["surface"], 6), (ALERT_RED, 2.5)):  # surface halo keeps shared borders readable
            fig.add_trace(go.Choropleth(
                geojson=geo(), featureidkey="properties.shapeISO", locations=hit, z=[1] * len(hit),
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
                marker_line_color=color, marker_line_width=width, hoverinfo="skip"))
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="rgba(0,0,0,0)")
    fig.update_layout(height=470, margin=dict(l=0, r=0, t=0, b=40))
    return fig


def hourly_chart(starts, values, rhythm, actual, mark=None):
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
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), bargap=0, hovermode="x unified",
                      yaxis=dict(tickformat=".0%", range=[0, top]), legend=dict(orientation="h", y=-0.25))
    return fig
