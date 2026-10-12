"""Streamlit GUI: streamlit run app.py

Reads only files written by `python -m airraid backtest|forecast` (results/), so it opens
instantly and cannot leak anything into the models.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from airraid import paths
from airraid.regions import BY_CODE, CODES, EXCLUDED

RESULTS = paths.RESULTS
GEOJSON = paths.ASSETS / "ukraine_adm1.geojson"

# Reference palette (dataviz skill): one blue ramp for probability, fixed categorical slots per model.
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
ALERT_RED = "#d03b3b"   # status "critical": always paired with the label "alert happened"
NEUTRAL = "#8a8985"
MODELS = {  # column -> (label, colour); colour follows the model in every chart
    "gbm_both": ("Boosting + both channels", "#e87ba4"),
    "gbm_none": ("Boosting, alert history only", "#eb6834"),
    "logistic": ("Logistic regression", "#1baf7a"),
    "gbm_kpszsu": ("Boosting + Air Force", "#eda100"),
    "gbm_alertmap": ("Boosting + alert-map (main)", "#2a78d6"),
    "persistence": ("Persistence (as now)", "#008300"),
    "climatology": ("Climatology (28-day hourly rate)", NEUTRAL),
}
# First entry = main model, picked on the validation weeks (see airraid/backtest.py MAIN_MODEL).
SOURCE_SETS = {"Alert-map only (main)": "gbm_alertmap", "Both channels": "gbm_both", "Air Force only": "gbm_kpszsu",
               "No Telegram": "gbm_none", "Climatology baseline": "climatology"}

st.set_page_config(page_title="Air raid alert forecast", layout="wide")


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


@st.cache_data
def load(stamp: tuple):
    """`stamp` (file modification times) makes the cache refresh when results are rewritten."""
    pred = pd.read_parquet(RESULTS / "predictions.parquet")
    pred["code"] = pred["region"].map(lambda i: CODES[i])
    fc = pd.read_parquet(RESULTS / "forecast_latest.parquet") if (RESULTS / "forecast_latest.parquet").exists() else None
    if fc is not None:
        fc["code"] = fc["region"].map(lambda i: CODES[i])
    geo = rewind_for_plotly(json.loads(GEOJSON.read_text(encoding="utf-8")))
    extra = {}
    for name in ("metrics_overall", "metrics_by_horizon", "metrics_by_horizon_quiet", "metrics_by_region"):
        f = RESULTS / f"{name}.csv"
        extra[name] = pd.read_csv(f) if f.exists() else None
    hourly = pd.read_parquet(RESULTS / "hourly_alerts.parquet") if (RESULTS / "hourly_alerts.parquet").exists() else None
    health = json.loads((RESULTS / "source_health.json").read_text()) if (RESULTS / "source_health.json").exists() else None
    return pred, fc, geo, extra, hourly, health


def kyiv(ts: pd.Timestamp) -> str:
    return ts.tz_convert("Europe/Kyiv").strftime("%a %d %b %H:%M")


def ukraine_map(geo, codes, probs, actual=None, title=""):
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.shapeISO", locations=list(EXCLUDED), z=[0] * len(EXCLUDED),
        colorscale=[[0, "#d9d8d4"], [1, "#d9d8d4"]], showscale=False, marker_line_color="white", marker_line_width=1,
        hovertemplate="%{location}: not forecast (no usable alert data)<extra></extra>"))
    names = [BY_CODE[c].name for c in codes]
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.shapeISO", locations=codes, z=probs, zmin=0, zmax=1,
        colorscale=[[i / (len(BLUES) - 1), c] for i, c in enumerate(BLUES)], marker_line_color="white",
        marker_line_width=1, text=names, colorbar=dict(title="P(alert)", tickformat=".0%", len=0.8),
        hovertemplate="%{text}<br>P(alert) = %{z:.0%}<extra></extra>"))
    if actual is not None and actual.any():
        hit = [c for c, a in zip(codes, actual) if a == 1]
        fig.add_trace(go.Choropleth(
            geojson=geo, featureidkey="properties.shapeISO", locations=hit, z=[1] * len(hit),
            colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
            marker_line_color=ALERT_RED, marker_line_width=3.5, name="alert happened",
            hovertemplate="%{location}: alert happened<extra></extra>"))
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=30, b=0), title=title,
                      paper_bgcolor="rgba(0,0,0,0)", geo_bgcolor="rgba(0,0,0,0)")
    return fig


def line_chart(df, x, cols, ytitle, yfmt=None, ref_zero=False):
    fig = go.Figure()
    for col in cols:
        label, colour = MODELS[col]
        dash = "dash" if col == "climatology" else "solid"
        fig.add_trace(go.Scatter(x=df[x], y=df[col], name=label, mode="lines+markers",
                                 line=dict(color=colour, width=2, dash=dash), marker=dict(size=8),
                                 hovertemplate=f"{label}: %{{y:.3f}}<extra></extra>"))
    if ref_zero:
        fig.add_hline(y=0, line=dict(color=NEUTRAL, width=1, dash="dot"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(title=ytitle, tickformat=yfmt),
                      xaxis=dict(title="hours ahead", dtick=2), legend=dict(orientation="h", y=-0.25), hovermode="x unified",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


pred, fc, geo, extra, hourly, health = load(tuple(f.stat().st_mtime for f in sorted(RESULTS.glob("*"))))
test = pred[pred["period"] == "test"]
issue_times = sorted(test["t"].unique())

st.title("Air raid alerts in Ukraine: 24-hour forecast")
st.caption(f"Per region, the probability of an air raid alert during each of the next 24 hours. "
           f"Test period {kyiv(issue_times[0])} – {kyiv(issue_times[-1])} (Kyiv time), never seen in training. "
           "Alerts: eTryvoga volunteer data. Telegram: @kpszsu (Air Force), @povitryanatrivogaaa.")

tab_map, tab_acc, tab_src, tab_data = st.tabs(["Map replay", "Accuracy", "Sources", "Data"])

with tab_map:
    LATEST = "Latest forecast"
    options = [pd.Timestamp(t) for t in issue_times] + ([LATEST] if fc is not None else [])
    c1, c2, c3 = st.columns([5, 2, 2])
    choice = c1.select_slider("Forecast issued at (Kyiv time); the right end is the latest forecast, with no outcome yet",
                              options=options, value=options[-1],
                              format_func=lambda o: "▶ latest forecast" if o == LATEST else kyiv(o))
    h = c2.slider("Hours ahead", 1, 24, 6)
    model = SOURCE_SETS[c3.radio("Model", list(SOURCE_SETS), index=0)]

    if choice == LATEST:
        rows = fc[fc["h"] == h].sort_values("region")
        probs = rows["p"].to_numpy() if model != "climatology" else rows["p_climatology"].to_numpy()
        actual = None
        issued = rows["t"].iat[0]
        note = ("Latest forecast: uses Telegram posts up to the issue time; the outcome is not known yet. "
                "It is computed for the main model (alert-map) and climatology only; other choices show the main model.")
    else:
        rows = test[(test["t"] == choice) & (test["h"] == h)].sort_values("region")
        probs = rows[f"p_{model}"].to_numpy()
        actual = rows["y"].to_numpy()
        issued = choice
        note = None
    target = issued + pd.Timedelta(hours=h - 1)  # h=1 is the hour right after issuing
    left, right = st.columns([3, 1])
    left.plotly_chart(ukraine_map(geo, list(rows["code"]), probs, actual,
                                  f"Hour starting {kyiv(target)}  ·  issued {kyiv(issued)}"),
                      use_container_width=True)
    with right:
        st.markdown("**At this moment**")
        st.metric("Regions forecast ≥ 50%", int((probs >= 0.5).sum()))
        if actual is not None:
            st.metric("Regions with an alert (red outline)", int(actual.sum()))
            b_model = float(np.mean((probs - actual) ** 2))
            b_clim = float(np.mean((rows["p_climatology"].to_numpy() - actual) ** 2))
            st.metric("Brier score now (lower is better)", f"{b_model:.3f}", f"{b_model - b_clim:+.3f} vs climatology",
                      delta_color="inverse")
        if note:
            st.info(note)
        st.caption("Fill = forecast probability. Red outline = alert actually happened in that hour. "
                   "Grey = not forecast (Luhansk, Crimea: no usable alert data).")

    region = st.selectbox("Region timeline", [BY_CODE[c].name for c in CODES], index=CODES.index("UA-30"))
    rc = CODES.index(next(c for c in CODES if BY_CODE[c].name == region))
    if choice != LATEST:
        window = test[(test["region"] == rc) & (test["h"] == h)
                      & (test["t"].between(choice - pd.Timedelta(days=3), choice + pd.Timedelta(days=3)))].sort_values("t")
        tt = window["t"] + pd.Timedelta(hours=h - 1)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=tt.dt.tz_convert("Europe/Kyiv"), y=window["y"], name="alert happened",
                             marker_color=ALERT_RED, opacity=0.25, hovertemplate="%{x}: alert<extra></extra>"))
        for col in ("climatology", model if model != "climatology" else None):
            if col:
                fig.add_trace(go.Scatter(x=tt.dt.tz_convert("Europe/Kyiv"), y=window[f"p_{col}"], name=MODELS[col][0],
                                         line=dict(color=MODELS[col][1], width=2, dash="dash" if col == "climatology" else "solid")))
        fig.add_vline(x=target.tz_convert("Europe/Kyiv"), line=dict(color=NEUTRAL, width=1, dash="dot"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10), bargap=0,
                          title=f"{region}: forecast made {h}h ahead vs what happened (±3 days)",
                          yaxis=dict(tickformat=".0%", range=[0, 1]), legend=dict(orientation="h", y=-0.3),
                          hovermode="x unified", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    else:
        one = fc[fc["region"] == rc].sort_values("h")
        fig = go.Figure()
        x = (one["t"] + pd.to_timedelta(one["h"] - 1, unit="h")).dt.tz_convert("Europe/Kyiv")
        fig.add_trace(go.Scatter(x=x, y=one["p"], name=MODELS["gbm_alertmap"][0], line=dict(color=MODELS["gbm_alertmap"][1], width=2)))
        fig.add_trace(go.Scatter(x=x, y=one["p_climatology"], name=MODELS["climatology"][0],
                                 line=dict(color=NEUTRAL, width=2, dash="dash")))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10), title=f"{region}: next 24 hours",
                          yaxis=dict(tickformat=".0%", range=[0, 1]), legend=dict(orientation="h", y=-0.3),
                          hovermode="x unified", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

with tab_acc:
    st.markdown("**Brier skill vs climatology by forecast horizon** (test period; above 0 = better than the "
                "28-day hourly rate of the region, 1 = perfect)")
    quiet = st.radio("Moments scored", ["All issue times", "Only when no alert is running at issue time"],
                     horizontal=True, help="With an alert running, the next hour is trivially 'yes'. "
                     "Quiet moments ask the harder question: will a new alert start?")
    bh = extra["metrics_by_horizon_quiet" if quiet.startswith("Only") else "metrics_by_horizon"]
    if bh is not None:
        wide = bh.pivot(index="h", columns="model", values="brier_skill").reset_index()
        # The next hour is far easier than the rest; on one axis it would flatten every other horizon.
        st.markdown("Next hour (h = 1)")
        tiles = st.columns(4)
        for tile, col in zip(tiles, ["gbm_alertmap", "gbm_none", "gbm_both", "logistic"]):
            tile.metric(MODELS[col][0], f"{wide.loc[wide['h'] == 1, col].iat[0]:.3f}")
        st.markdown("2 to 24 hours ahead")
        st.plotly_chart(line_chart(wide[wide["h"] >= 2], "h", ["gbm_alertmap", "gbm_none", "logistic", "climatology"],
                                   "Brier skill", ref_zero=True), use_container_width=True)
    ov = extra["metrics_overall"]
    if ov is not None:
        st.markdown("**Overall scores** (validation = 4 weeks used for choices; test = last 4 weeks, run once)")
        show = ov.assign(model=ov["model"].map(lambda m: MODELS.get(m, (m,))[0]))
        st.dataframe(show.round(4), hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Calibration** (test, main model): when it says 30%, is there an alert 30% of the time?")
        b = np.minimum((test["p_gbm_alertmap"] * 10).astype(int), 9)
        cal = test.groupby(b).agg(predicted=("p_gbm_alertmap", "mean"), observed=("y", "mean"), n=("y", "size"))
        fig = go.Figure([go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(color=NEUTRAL, dash="dot"), name="perfect"),
                         go.Scatter(x=cal["predicted"], y=cal["observed"], mode="lines+markers", name=MODELS["gbm_alertmap"][0],
                                    line=dict(color=MODELS["gbm_alertmap"][1], width=2), marker=dict(size=8),
                                    customdata=cal["n"], hovertemplate="predicted %{x:.0%} → observed %{y:.0%} (n=%{customdata})<extra></extra>")])
        fig.update_layout(height=360, xaxis=dict(title="predicted probability", tickformat=".0%"),
                          yaxis=dict(title="observed frequency", tickformat=".0%"), margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=-0.25), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown("**Brier skill by region** (test, main model: boosting + alert-map)")
        br = extra["metrics_by_region"]
        if br is not None:
            r = br[br["model"] == "gbm_alertmap"].sort_values("brier_skill")
            fig = go.Figure(go.Bar(x=r["brier_skill"], y=r["region_name"], orientation="h", marker_color=MODELS["gbm_alertmap"][1],
                                   hovertemplate="%{y}: %{x:.2f}<extra></extra>"))
            fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(title="Brier skill vs climatology"),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

with tab_src:
    st.markdown("**Does Telegram help?** Brier skill by horizon for the same model with different input sources "
                "(target is always the eTryvoga alert history)")
    if bh is not None:
        st.markdown("Next hour (h = 1)")
        tiles = st.columns(4)
        for tile, col in zip(tiles, ["gbm_none", "gbm_kpszsu", "gbm_alertmap", "gbm_both"]):
            tile.metric(MODELS[col][0], f"{wide.loc[wide['h'] == 1, col].iat[0]:.3f}")
        st.markdown("2 to 24 hours ahead")
        st.plotly_chart(line_chart(wide[wide["h"] >= 2], "h", ["gbm_both", "gbm_none", "gbm_kpszsu", "gbm_alertmap"],
                                   "Brier skill", ref_zero=True), use_container_width=True)
        st.caption("Scores follow the 'Moments scored' choice on the Accuracy tab. Telegram helps mainly in the "
                   "first 1-3 hours, at moments with no alert running.")
    if health:
        st.markdown("**Source health**")
        st.dataframe(pd.DataFrame(health), hide_index=True, use_container_width=True)

with tab_data:
    if hourly is not None:
        st.markdown("**Share of hours under alert, by region and hour of day** (Kyiv time, 2026)")
        hh = hourly.copy()
        hh.index = pd.DatetimeIndex(hh.index).tz_convert("Europe/Kyiv")
        prof = hh.groupby(hh.index.hour).mean().T
        prof.index = [BY_CODE[c].name for c in prof.index]
        prof = prof.loc[prof.mean(axis=1).sort_values().index]
        fig = go.Figure(go.Heatmap(z=prof.values, x=prof.columns, y=prof.index, zmin=0, zmax=1,
                                   colorscale=[[i / (len(BLUES) - 1), c] for i, c in enumerate(BLUES)],
                                   colorbar=dict(tickformat=".0%"), xgap=2, ygap=2,
                                   hovertemplate="%{y}, %{x}:00 → %{z:.0%}<extra></extra>"))
        fig.update_layout(height=620, xaxis=dict(title="hour of day (Kyiv)", dtick=2), margin=dict(l=10, r=10, t=10, b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.markdown("**Share of region-hours under alert, by week**")
        wk = hourly.mean(axis=1).resample("W").mean()
        fig = go.Figure(go.Scatter(x=wk.index.tz_convert("Europe/Kyiv"), y=wk.values, mode="lines+markers",
                                   line=dict(color=BLUES[4], width=2), marker=dict(size=8),
                                   hovertemplate="week of %{x|%d %b}: %{y:.0%}<extra></extra>"))
        fig.update_layout(height=300, yaxis=dict(tickformat=".0%"), margin=dict(l=10, r=10, t=10, b=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

st.caption("Boundaries: geoBoundaries (UKR ADM1, © OpenStreetMap contributors, ODbL).")
