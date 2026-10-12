"""Streamlit GUI: python -m airraid gui

One page, four questions: what is this and does it work (header), explore the forecast, how good is it,
where does the data come from, and how it was tested. Reads only files written by the pipeline
(results/), so it opens instantly and cannot leak anything into the models.
"""
from __future__ import annotations

import json
from datetime import datetime, time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from airraid import paths
from airraid.regions import BY_CODE, CODES, EXCLUDED

RESULTS = paths.RESULTS
GEOJSON = paths.ASSETS / "ukraine_adm1.geojson"
KYIV = "Europe/Kyiv"
NO_TOOLBAR = {"displayModeBar": False}

# Reference palette (dataviz skill). Red is reserved for "an alert happened".
BLUE, AQUA, GREY, ALERT_RED = "#2a78d6", "#1baf7a", "#8a8985", "#d03b3b"
THEMES = {  # probability ramp runs from the page surface towards high contrast in both themes
    "light": dict(ramp=["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
                  surface="#ffffff", excluded="#e3e2de"),
    "dark": dict(ramp=["#1b2a40", "#1c3f6e", "#1c5cab", "#2a78d6", "#5598e7", "#9ec5f4", "#cde2fb"],
                 surface="#0e1117", excluded="#2a2b31"),
}
MODEL_NAMES = {
    "main": "Main model", "gbm_none": "Alert history only", "gbm_alertmap": "+ alert-map channel",
    "gbm_kpszsu": "+ Air Force channel", "gbm_both": "+ both channels", "logistic": "Logistic regression",
    "persistence": "Persistence (as now)", "climatology": "Usual daily rhythm",
}

st.set_page_config(page_title="Air raid alert forecast", layout="wide")


# ---------------------------------------------------------------- data

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
    fc = pd.read_parquet(RESULTS / "forecast_latest.parquet")
    if "p_main" not in fc:
        fc["p_main"] = fc["p"]
    unc = pd.read_csv(RESULTS / "uncertainty.csv", dtype={"h": str})
    health = {h["source"]: h for h in json.loads((RESULTS / "source_health.json").read_text())}
    data = {
        "pred": pred, "test": pred[pred["period"] == "test"], "fc": fc, "unc": unc, "health": health,
        "geo": rewind_for_plotly(json.loads(GEOJSON.read_text(encoding="utf-8"))),
        "overall": pd.read_csv(RESULTS / "metrics_overall.csv"),
        "by_region": pd.read_csv(RESULTS / "metrics_by_region.csv"),
        "agreement": pd.read_csv(RESULTS / "alert_source_agreement.csv"),
        "hourly": pd.read_parquet(RESULTS / "hourly_alerts.parquet"),
    }
    data["presets"] = presets(data["test"])
    return data


PRESET_RULES = {
    "Biggest attack": "the moment followed by the most region-hours under alert",
    "Quietest day": "the moment followed by the fewest region-hours under alert",
    "A good forecast": "where the model beat the usual daily rhythm by the widest margin over the following 24 hours",
    "A missed forecast": "where the model did worst against the usual daily rhythm over the following 24 hours",
}


def presets(test: pd.DataFrame) -> dict:
    """Example moments from the test period, chosen by the rules above (a hit is always shown with a miss)."""
    g = test.assign(e_main=(test["p_main"] - test["y"]) ** 2, e_clim=(test["p_climatology"] - test["y"]) ** 2)
    per_t = g.groupby("t").agg(alerts=("y", "sum"), e_main=("e_main", "sum"), e_clim=("e_clim", "sum"))
    per_t = per_t[g.groupby("t").size() == 24 * 24]  # moments with all 24 hours known
    gain = per_t["e_clim"] - per_t["e_main"]
    return {"Biggest attack": per_t["alerts"].idxmax(), "Quietest day": per_t["alerts"].idxmin(),
            "A good forecast": gain.idxmax(), "A missed forecast": gain.idxmin()}


def ci(unc, metric, period, subset, h):
    r = unc[(unc["metric"] == metric) & (unc["period"] == period) & (unc["subset"] == subset) & (unc["h"] == str(h))]
    return float(r["point"].iat[0]), float(r["lo"].iat[0]), float(r["hi"].iat[0])


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


def show(fig):
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True, config=NO_TOOLBAR)


# ---------------------------------------------------------------- charts

def ukraine_map(geo, codes, probs, actual, value_label):
    th = theme()
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.shapeISO", locations=list(EXCLUDED), z=[0] * len(EXCLUDED),
        colorscale=[[0, th["excluded"]], [1, th["excluded"]]], showscale=False,
        marker_line_color=th["surface"], marker_line_width=1,
        hovertemplate="%{location}: not forecast (no usable alert data)<extra></extra>"))
    names = [BY_CODE[c].name for c in codes]
    outcome = [""] * len(codes) if actual is None else [" · alert happened" if a else " · no alert" for a in actual]
    fig.add_trace(go.Choropleth(
        geojson=geo, featureidkey="properties.shapeISO", locations=codes, z=probs, zmin=0, zmax=1,
        colorscale=[[i / (len(th["ramp"]) - 1), c] for i, c in enumerate(th["ramp"])],
        marker_line_color=th["surface"], marker_line_width=1, customdata=np.array([names, outcome]).T,
        colorbar=dict(title=value_label, tickformat=".0%", orientation="h", x=0.5, y=-0.02, len=0.5, thickness=10),
        hovertemplate="%{customdata[0]}: %{z:.0%}%{customdata[1]}<extra></extra>"))
    if actual is not None and actual.any():
        hit = [c for c, a in zip(codes, actual) if a == 1]
        for color, width in ((th["surface"], 6), (ALERT_RED, 2.5)):  # surface halo keeps shared borders readable
            fig.add_trace(go.Choropleth(
                geojson=geo, featureidkey="properties.shapeISO", locations=hit, z=[1] * len(hit),
                colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
                marker_line_color=color, marker_line_width=width, hoverinfo="skip"))
    fig.update_geos(fitbounds="locations", visible=False, bgcolor="rgba(0,0,0,0)")
    fig.update_layout(height=470, margin=dict(l=0, r=0, t=0, b=40))
    return fig


def hourly_chart(starts, values, rhythm, actual, mark=None):
    """Forecast per hour (line) vs the usual daily rhythm (dashed); a red strip marks hours with an alert."""
    mid = (starts + pd.Timedelta(minutes=30)).dt.tz_convert(KYIV)
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
        fig.add_vrect(x0=mark.tz_convert(KYIV), x1=(mark + pd.Timedelta(hours=1)).tz_convert(KYIV),
                      fillcolor=BLUE, opacity=0.12, line_width=0)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), bargap=0, hovermode="x unified",
                      yaxis=dict(tickformat=".0%", range=[0, top]), legend=dict(orientation="h", y=-0.25))
    return fig


# ---------------------------------------------------------------- page

D = load(tuple(f.stat().st_mtime for f in sorted(RESULTS.glob("*"))))
test, fc, unc, health = D["test"], D["fc"], D["unc"], D["health"]
issue_times = sorted(test["t"].unique())
data_end = fc["t"].iat[0]

st.title("Air raid alerts in Ukraine: a 24-hour forecast")
st.markdown(
    "For each of 24 regions, the chance of an air raid alert in each of the next 24 hours. Tested hour by hour on "
    f"the last four weeks (**{kyiv(issue_times[0], '%d %b')} – {kyiv(data_end, '%d %b %Y')}**), each week forecast "
    "by a model trained only on earlier data.  \n"
    "**Data:** alert history from the volunteer eTryvoga channel "
    "([open dataset](https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset)) · Telegram posts of the "
    "[Air Force of Ukraine](https://t.me/s/kpszsu) and the [alert-map channel](https://t.me/s/povitryanatrivogaaa). "
    "[More about the data](#data)")
st.info(f"**A snapshot, not a live service.** The data ends on {kyiv(data_end)} (Kyiv). This is a research "
        "prototype, not a warning system: always follow official air raid alerts.", icon="ℹ️")

nh, nh_lo, nh_hi = ci(unc, "main_vs_climatology", "test", "all", 1)
nq, nq_lo, nq_hi = ci(unc, "main_vs_climatology", "test", "quiet", 1)
lg, lg_lo, lg_hi = ci(unc, "main_vs_climatology", "test", "all", "4-24")
tg, tg_lo, tg_hi = ci(unc, "alertmap_minus_none", "test", "quiet", 1)
tl, tl_lo, tl_hi = ci(unc, "alertmap_minus_none", "test", "quiet", "4-24")
c1, c2, c3 = st.columns(3)
with c1.container(border=True):
    st.markdown(f"#### Next hour: {pct(nh, 0)} better\nthan the region's usual daily rhythm, mostly because a running "
                f"alert continues. With no alert running: **{pct(nq)}** ({pct(nq_lo)}–{pct(nq_hi)}).")
with c2.container(border=True):
    st.markdown(f"#### 4–24 hours ahead: {pct(lg)} better\n({pct(lg_lo)}–{pct(lg_hi)}). Further ahead the usual "
                "daily rhythm (night raids, front-line regions) is hard to beat.")
with c3.container(border=True):
    st.markdown(f"#### Telegram helps the first 1–3 hours\n**+{tg * 100:.1f} points** for the next hour with no alert "
                f"running ({tg_lo * 100:+.1f} to {tg_hi * 100:+.1f}); from 4 hours on nothing measurable "
                f"({tl * 100:+.1f}).")
st.caption("Ranges are 95%. Jump to: [Explore the forecast](#explore) · [How good is it?](#how-good) · "
           "[Where does the data come from?](#data) · [How it was tested, and its limits](#limits)")


@st.fragment
def explorer():
    st.header("Explore the forecast", anchor="explore")
    choices = ["Latest forecast", *D["presets"], "Pick a date"]
    mode = st.pills("Moment", choices, default="Latest forecast", label_visibility="collapsed") or "Latest forecast"
    if mode == "Latest forecast":
        issued = data_end
    elif mode == "Pick a date":
        first, last = issue_times[0].tz_convert(KYIV), issue_times[-1].tz_convert(KYIV)
        d1, d2 = st.columns([2, 1])
        day = d1.date_input("Day (Kyiv)", value=datetime(2026, 9, 30).date(), min_value=first.date(), max_value=last.date())
        hour = d2.selectbox("Forecast made at", list(range(24)), index=3, format_func=lambda h: f"{h:02d}:00")
        wanted = pd.Timestamp(datetime.combine(day, time(hour)), tz=KYIV).tz_convert("UTC")
        issued = min(issue_times, key=lambda t: abs(t - wanted))
    else:
        issued = D["presets"][mode]
        st.caption(f"{mode}: {PRESET_RULES[mode]}, in the test period. Move 'Hours ahead' or see the region chart below for the "
                   "whole 24 hours.")

    a, b = st.columns([3, 2], vertical_alignment="bottom")
    h = a.slider("Hours ahead", 1, 24, 1, help="1 = the hour right after the forecast was made.")
    show_rhythm = b.segmented_control("Colour the map by", ["Forecast", "Usual daily rhythm"], default="Forecast") == "Usual daily rhythm"

    latest = mode == "Latest forecast"
    src = fc if latest else test[test["t"] == issued]
    rows = src[src["h"] == h].sort_values("region")
    codes = [CODES[i] for i in rows["region"]]
    probs = rows["p_climatology" if show_rhythm else "p_main"].to_numpy()
    actual = None if latest else rows["y"].to_numpy()
    target = issued + pd.Timedelta(hours=h - 1)
    skill, s_lo, s_hi = ci(unc, "main_vs_climatology", "test", "all", h)

    outcome = ("The outcome is not in the data yet." if actual is None
               else f"Actually under alert: **{int(actual.sum())}** (red outline).")
    st.markdown(f"Forecast made **{kyiv(issued)}** for **{hour_span(target)}** ({h} h ahead). "
                f"Expected regions under alert: **{probs.sum():.1f}** of 24. {outcome}  \n"
                f"At {h} h ahead the model is on average **{pct(skill)}** better than the usual daily rhythm "
                f"(test, 95%: {pct(s_lo)}–{pct(s_hi)}).")
    show(ukraine_map(D["geo"], codes, probs, actual, "usual daily rhythm" if show_rhythm else "chance of an alert"))
    st.caption("Colour = chance of an alert in that hour. Red outline = an alert actually happened. "
               "Grey = not forecast (Luhansk: permanent alert since 2022; Crimea: no data). Switch to "
               "'Usual daily rhythm' to see how much of the map is simply each region's typical pattern.")

    names = [BY_CODE[c].name for c in CODES]
    r1, r2 = st.columns([1, 3], vertical_alignment="bottom")
    region = r1.selectbox("Region", names, index=CODES.index("UA-30"))
    rc = names.index(region)
    r2.markdown(f"**{region}: the 24 hourly forecasts made at {kyiv(issued)}** (shaded = the map hour)")
    one = src[src["region"] == rc].sort_values("h")
    show(hourly_chart(one["t"] + pd.to_timedelta(one["h"] - 1, unit="h"), one["p_main"].to_numpy(),
                      one["p_climatology"].to_numpy(), None if latest else one["y"].to_numpy(), mark=target))
    if not latest:
        with st.expander(f"Track record in {region}: forecasts made {h} h ahead, ±3 days around this moment"):
            w = test[(test["region"] == rc) & (test["h"] == h)
                     & test["t"].between(issued - pd.Timedelta(days=3), issued + pd.Timedelta(days=3))].sort_values("t")
            show(hourly_chart(w["t"] + pd.Timedelta(hours=h - 1), w["p_main"].to_numpy(), w["p_climatology"].to_numpy(),
                              w["y"].to_numpy(), mark=target))


explorer()

# ---------------------------------------------------------------- how good
st.header("How good is it?", anchor="how-good")
st.markdown("Scores compare the forecast with **the usual daily rhythm**: the share of hours with an alert in that "
            "region at that hour of day over the previous 28 days. 0% = no better than that rhythm; the bands are "
            "95% ranges from resampling whole days of the test period.")
u = unc[(unc["metric"] == "main_vs_climatology") & (unc["period"] == "test")]
fig = make_subplots(rows=1, cols=2, column_widths=[0.2, 0.8], horizontal_spacing=0.08,
                    subplot_titles=["Next hour", "2–24 hours ahead"])
for subset, color, label in (("all", BLUE, "all moments"), ("quiet", AQUA, "no alert running at forecast time")):
    s = u[u["subset"] == subset]
    one = s[s["h"] == "1"]
    fig.add_trace(go.Scatter(x=[label], y=one["point"], mode="markers", marker=dict(color=color, size=11),
                             error_y=dict(type="data", array=one["hi"] - one["point"], arrayminus=one["point"] - one["lo"]),
                             showlegend=False, hovertemplate=label + ": %{y:.1%}<extra></extra>"), row=1, col=1)
    s = s[s["h"].str.isdigit()].assign(h=lambda d: d["h"].astype(int)).query("h >= 2").sort_values("h")
    fig.add_trace(go.Scatter(x=pd.concat([s["h"], s["h"][::-1]]), y=pd.concat([s["hi"], s["lo"][::-1]]), fill="toself",
                             fillcolor=color, opacity=0.15, line=dict(width=0), hoverinfo="skip", showlegend=False),
                  row=1, col=2)
    fig.add_trace(go.Scatter(x=s["h"], y=s["point"], mode="lines", name=label, line=dict(color=color, width=2.5),
                             hovertemplate=label + ", %{x} h: %{y:.1%}<extra></extra>"), row=1, col=2)
fig.add_hline(y=0, line=dict(color=GREY, width=1, dash="dot"), row=1, col=2,
              annotation_text="usual daily rhythm", annotation_position="bottom right")
fig.update_yaxes(tickformat=".0%", row=1, col=1, rangemode="tozero")
fig.update_yaxes(tickformat=".1%", row=1, col=2)
fig.update_xaxes(title_text="hours ahead", dtick=2, row=1, col=2)
fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=-0.25))
st.markdown(f"**The next hour is where the forecast is good ({pct(nh, 0)}); from 4 hours on it is only "
            f"{pct(lg)} better than the usual daily rhythm.**")
show(fig)

st.markdown("**Telegram helps only the first 1–3 hours**: the gain over the same model without Telegram, at moments "
            "with no alert running (alert-map channel). The model choice was made on the validation weeks, then the "
            "test weeks were scored once.")
fig = go.Figure()
for period, color, dash in (("validation", GREY, "dash"), ("test", BLUE, "solid")):
    s = unc[(unc["metric"] == "alertmap_minus_none") & (unc["period"] == period) & (unc["subset"] == "quiet")]
    s = s[s["h"].str.isdigit()].assign(h=lambda d: d["h"].astype(int)).sort_values("h")
    fig.add_trace(go.Scatter(x=pd.concat([s["h"], s["h"][::-1]]), y=pd.concat([s["hi"], s["lo"][::-1]]), fill="toself",
                             fillcolor=color, opacity=0.12, line=dict(width=0), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=s["h"], y=s["point"], mode="lines", name=f"{period} weeks",
                             line=dict(color=color, width=2.5, dash=dash),
                             hovertemplate=period + ", %{x} h: %{y:+.1%}<extra></extra>"))
fig.add_hline(y=0, line=dict(color=GREY, width=1, dash="dot"))
fig.add_vline(x=3.5, line=dict(color=GREY, width=1), annotation_text="main model uses Telegram up to here",
              annotation_position="top right")
fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h", y=-0.3),
                  xaxis=dict(title="hours ahead", dtick=2), yaxis=dict(title="gain (points)", tickformat="+.1%"))
show(fig)
kp, kp_lo, kp_hi = ci(unc, "kpszsu_minus_none", "test", "quiet", 1)
st.caption(f"The Air Force channel (@kpszsu) adds less: {kp * 100:+.1f} points for the next hour "
           f"(95%: {kp_lo * 100:+.1f} to {kp_hi * 100:+.1f}), so the main model uses only the alert-map channel.")

c1, c2 = st.columns(2)
with c1:
    st.markdown("**Are the probabilities honest?** When the forecast says 30%, an alert follows about 30% of the time.")
    fig = go.Figure([go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(color=GREY, dash="dot"), name="perfect")])
    for col, color, label in (("p_main", BLUE, "forecast"), ("p_climatology", GREY, "usual daily rhythm")):
        b = np.minimum((test[col] * 10).astype(int), 9)
        cal = test.groupby(b).agg(predicted=(col, "mean"), observed=("y", "mean"), n=("y", "size"))
        fig.add_trace(go.Scatter(x=cal["predicted"], y=cal["observed"], mode="lines+markers", name=label,
                                 line=dict(color=color, width=2.5 if col == "p_main" else 1.5), customdata=cal["n"],
                                 hovertemplate=label + ": said %{x:.0%} → happened %{y:.0%} (n=%{customdata})<extra></extra>"))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.25),
                      xaxis=dict(title="forecast", tickformat=".0%", range=[0, 1], constrain="domain"),
                      yaxis=dict(title="share with an alert", tickformat=".0%", range=[0, 1], scaleanchor="x"))
    show(fig)
with c2:
    st.markdown("**By region** (test, % better than the usual daily rhythm)")
    alerts = test[test["h"] == 1].groupby("region")["y"].mean()
    br = D["by_region"]
    br = br[(br["model"] == "main") & br["region"].map(alerts).gt(0)].sort_values("brier_skill")
    none = [BY_CODE[CODES[i]].name for i in alerts[alerts == 0].index]
    fig = go.Figure(go.Bar(x=br["brier_skill"], y=br["region_name"], orientation="h",
                           marker_color=np.where(br["brier_skill"] > 0, BLUE, GREY),
                           hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(tickformat=".0%"))
    show(fig)
    if none:
        st.caption(f"Not shown: {', '.join(none)}, no alerts at all in the test period, so there is nothing to beat. "
                   "Grey bars: worse than the usual daily rhythm.")

with st.expander("All models and scores"):
    ov = D["overall"]
    tab = ov[ov["period"].isin(["test", "validation"])].pivot_table(index="model", columns="period",
                                                                     values=["brier_skill", "auc"])
    tab.columns = [f"{'% better' if m == 'brier_skill' else 'AUC'} ({p})" for m, p in tab.columns]
    tab.index = [MODEL_NAMES.get(m, m) for m in tab.index]
    st.dataframe(tab.sort_values("% better (validation)", ascending=False),
                 column_config={c: st.column_config.NumberColumn(format="percent" if "%" in c else "%.3f") for c in tab.columns})
    st.caption("% better = Brier skill vs the usual daily rhythm over all hours ahead. AUC = how well the forecast ranks "
               "hours with and without an alert (0.5 = chance).")

# ---------------------------------------------------------------- data
st.header("Where does the data come from?", anchor="data")
e, k, m = health.get("etryvoga", {}), health.get("kpszsu", {}), health.get("povitryanatrivogaaa", {})
c1, c2, c3 = st.columns(3)
with c1.container(border=True):
    st.markdown(
        "**What we forecast: the alert history**  \n"
        "Oblast-level air raid alerts recorded by the volunteer eTryvoga channel, via the open "
        "[ukrainian-air-raid-sirens-dataset](https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset) "
        f"(fixed version). Feb 2022 – 12 Oct 2026, {e.get('records', 0):,} alerts.  \n"
        "The official record stops on 7 Sep 2026 and since December 2025 alerts are declared per district, "
        "so the two disagree on 19% of oblast-hours (e.g. Donetsk: official 99.8% of hours under alert, "
        "volunteer 28%).")
with c2.container(border=True):
    st.markdown(
        "**Signal: Air Force of Ukraine, [@kpszsu](https://t.me/s/kpszsu)**  \n"
        f"Official live threat tracks (drones, missiles, guided bombs) by region. {k.get('records', 0):,} posts, "
        f"1 Jan – 12 Oct 2026; {k.get('threat_posts_with_region', '?')} of threat posts matched to a region; "
        f"edited posts ({k.get('edited_posts', '?')}) left out. Adds little in the tests.")
with c3.container(border=True):
    st.markdown(
        "**Signal: alert-map channel, [@povitryanatrivogaaa](https://t.me/s/povitryanatrivogaaa)**  \n"
        f"Volunteer drone routes, missile tracks, explosions. {m.get('records', 0):,} posts, 1 Jan – 12 Oct 2026; "
        f"{m.get('threat_posts_with_region', '?')} of threat posts matched to a region; edited posts "
        f"({m.get('edited_posts', '?')}, mostly map images) left out. Used by the main model for the next 1–3 hours.")

hh = D["hourly"].copy()
hh.index = pd.DatetimeIndex(hh.index).tz_convert(KYIV)
prof = hh.groupby(hh.index.hour).mean().T
prof.index = [BY_CODE[c].name for c in prof.index]
prof = prof.loc[prof.mean(axis=1).sort_values().index]
th = theme()
st.markdown("**The daily rhythm the forecast has to beat**: share of hours under alert by region and hour of day "
            "(Kyiv time, 2026). Front-line regions and night hours dominate.")
fig = go.Figure(go.Heatmap(z=prof.values, x=prof.columns, y=prof.index, zmin=0, zmax=1, xgap=2, ygap=2,
                           colorscale=[[i / (len(th["ramp"]) - 1), c] for i, c in enumerate(th["ramp"])],
                           colorbar=dict(tickformat=".0%", thickness=10),
                           hovertemplate="%{y}, %{x}:00 → %{z:.0%}<extra></extra>"))
fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(title="hour of day (Kyiv)", dtick=2))
show(fig)
with st.expander("More: alerts by week, and official vs volunteer data by region"):
    wk = D["hourly"].mean(axis=1).resample("W-SUN", label="left").agg(["mean", "size"])
    wk = wk[wk["size"] == 7 * 24]  # whole weeks only
    fig = go.Figure(go.Scatter(x=wk.index.tz_convert(KYIV), y=wk["mean"], mode="lines", line=dict(color=BLUE, width=2),
                               hovertemplate="week of %{x|%d %b}: %{y:.0%}<extra></extra>"))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(tickformat=".0%", rangemode="tozero",
                                                                                   title="region-hours under alert"))
    show(fig)
    ag = D["agreement"].rename(columns={"region": "Region", "official_alert_hours": "Official: share of hours",
                                        "volunteer_alert_hours": "Volunteer: share of hours", "agreement": "Hours agreeing"})
    st.dataframe(ag, hide_index=True, column_config={c: st.column_config.NumberColumn(format="percent")
                                                     for c in ag.columns if c != "Region"})
    st.caption("1 Jun – 7 Sep 2026; official = any district of the oblast under alert.")

# ---------------------------------------------------------------- method and limits
st.header("How it was tested, and its limits", anchor="limits")
c1, c2 = st.columns(2)
with c1:
    st.markdown("""
**No look-ahead**
- Every forecast uses only data from before the moment it is made: alert history, and Telegram posts by their publish time.
- Retrained weekly; each week is forecast by a model trained only on earlier weeks.
- The model was chosen on 4 validation weeks; the last 4 weeks (test) were scored once.
- An automated test rebuilds every input from data cut off at the forecast moment and requires identical values.
- Edited Telegram posts are left out: Telegram shows when a post was published, not when it was edited, and the
  alert-map channel updates route summaries in place. Keeping them made that channel look better on validation
  (+3.2% instead of +2.7%).
""")
with c2:
    st.markdown("""
**Limits**
- "Alert" means the volunteer record, which disagrees with the official one on 19% of oblast-hours.
- The latest forecast is made at the end of the data snapshot, not now; alerts still running when the snapshot was
  taken are missing from it.
- Beyond a few hours the forecast is close to the usual daily rhythm; it cannot foresee a particular attack.
- Some regions are hardly predictable (Ivano-Frankivsk, Chernihiv: worse than the daily rhythm in the test weeks).
- Deleted Telegram posts are invisible; leaving out edited ones also drops some genuine information.
""")
with st.expander("Glossary"):
    st.markdown("""
- **Hours ahead**: which hour after the forecast is made; 1 = the hour right after it.
- **Usual daily rhythm** (climatology): share of hours with an alert in that region at that hour of day over the previous 28 days.
- **% better**: Brier skill score, 1 − (forecast error ÷ error of the usual daily rhythm); the error is the average of (probability − outcome)².
- **No alert running**: moments when the region had no alert at the time of the forecast; the question is whether a new one starts.
- **Validation / test**: 4 weeks used to choose the model / the last 4 weeks, scored once.
""")
st.caption("Code and full write-up: [github.com/LasonD/air-raids-analyzer](https://github.com/LasonD/air-raids-analyzer). "
           "Boundaries: geoBoundaries (UKR ADM1, © OpenStreetMap contributors, ODbL).")
