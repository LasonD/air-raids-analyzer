"""Model stages (5 Model & test, 6 Forecast) and the Result page."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from airraid import pipeline as P
from airraid.backtest import SHORT_HORIZON
from airraid.gui import common as C
from airraid.gui import stages as S
from airraid.regions import BY_CODE, CODES

PRESET_RULES = {
    "Biggest attack": "the moment followed by the most region-hours under alert",
    "Quietest day": "the moment followed by the fewest region-hours under alert",
    "A good forecast": "where the model beat the usual daily rhythm by the widest margin over the next 24 hours",
    "A missed forecast": "where the model did worst against the usual daily rhythm over the next 24 hours",
}


def presets(test: pd.DataFrame) -> dict:
    """Example moments from the committed test weeks (a hit is always shown with a miss)."""
    g = test.assign(e_main=(test["p_main"] - test["y"]) ** 2, e_clim=(test["p_climatology"] - test["y"]) ** 2)
    per_t = g.groupby("t").agg(alerts=("y", "sum"), e_main=("e_main", "sum"), e_clim=("e_clim", "sum"))
    per_t = per_t[g.groupby("t").size() == 24 * 24]
    gain = per_t["e_clim"] - per_t["e_main"]
    return {"Biggest attack": per_t["alerts"].idxmax(), "Quietest day": per_t["alerts"].idxmin(),
            "A good forecast": gain.idxmax(), "A missed forecast": gain.idxmin()}


def skill_table(pred: pd.DataFrame) -> pd.DataFrame:
    """% better than the usual daily rhythm by hours ahead, for all moments and for quiet ones."""
    rows = []
    for subset, g in (("all", pred), ("quiet", pred[pred["active_now"] == 0])):
        for h, gh in g.groupby("h"):
            rows.append({"subset": subset, "h": h, "skill": C.skill(gh["y"], gh["p_main"], gh["p_climatology"]),
                         "gain": C.skill(gh["y"], gh["p_short"], gh["p_climatology"])
                         - C.skill(gh["y"], gh["p_long"], gh["p_climatology"])})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 5 model & test

def walk_forward_chart(s: P.Settings, t: pd.Timestamp, blocks):
    cfg = s.config()
    fig = go.Figure()
    for i, (w, end) in enumerate(blocks):
        y = f"week of {C.kyiv(w, '%d %b')}"
        train_end = w - pd.Timedelta(hours=max(cfg.horizons))
        train_start = train_end - pd.Timedelta(days=cfg.train_days)
        fig.add_trace(go.Scatter(x=[C.local(train_start), C.local(train_end)], y=[y, y], mode="lines",
                                 line=dict(color=C.GREY, width=12), name="trained on", showlegend=i == 0,
                                 hovertemplate=f"trained on {C.kyiv(train_start, '%d %b')} – {C.kyiv(train_end, '%d %b')}<extra></extra>"))
        fig.add_trace(go.Scatter(x=[C.local(w), C.local(end)], y=[y, y], mode="lines", line=dict(color=C.BLUE, width=12),
                                 name="forecasts scored", showlegend=i == 0,
                                 hovertemplate=f"forecasts made {C.kyiv(w, '%d %b')} – {C.kyiv(end, '%d %b %H:%M')}<extra></extra>"))
    C.now_line(fig, t)
    fig.update_layout(height=60 + 40 * max(len(blocks), 1), margin=dict(l=10, r=10, t=25, b=10),
                      legend=dict(orientation="h", y=-0.3), yaxis=dict(autorange="reversed"))
    return fig


def model():
    s, t = C.settings(), C.now()
    clicked = C.stage_header("model", cheap=False)
    blocks = P.scoring_weeks(s.config(), t, st.session_state.get("n_weeks", 4))
    st.markdown(f"**Model:** gradient boosting, {C.main_model_name(s)}. Trained on the {s.train_days} days before "
                f"each week, then used for that week's forecasts; a forecast is scored once all its 24 hours have passed. "
                f"Settings are in the left panel.")
    if not blocks:
        st.warning("No forecast can be scored yet at this replay moment: move the clock later.")
        return
    C.show(walk_forward_chart(s, t, blocks))
    st.caption(f"{len(blocks)} weeks before the replay moment. A model never sees the week it forecasts, and inputs "
               "are cut at each forecast moment (checked by an automated test).")
    if clicked:
        bar, lines = st.progress(0.0, "starting…"), []
        with st.status("Training and scoring…", expanded=True):
            S.run_model(log=lambda m: (lines.append(m), st.write(m)), progress=lambda f, msg: bar.progress(f, msg))
        st.session_state["log_model"] = lines
        st.rerun()  # redraw the status line above
    if st.session_state.get("log_model"):
        with st.expander("Log of the last run"):
            st.markdown("\n".join(f"- {m}" for m in st.session_state["log_model"]))
    run = C.runs().get("model")
    if run is None:
        st.info(f"Press **Run** to train {2 if s.channels else 1} model(s) per week and score them "
                f"(about {10 * len(blocks) * (2 if s.channels else 1)} s the first time).")
        return
    pred = run["out"]
    if C.status("model") == "out of date":
        st.warning("Showing the previous run: the clock or the settings changed since. Press **Run again**.")
    tab = skill_table(pred)
    h1 = tab[(tab["h"] == 1)].set_index("subset")
    long = pred[pred["h"] >= 4]
    st.subheader("Scores of this run")
    c = st.columns(4)
    c[0].metric("Next hour", C.pct(h1.loc["all", "skill"]), help="% better than the usual daily rhythm")
    c[1].metric("Next hour, no alert running", C.pct(h1.loc["quiet", "skill"]))
    c[2].metric("4–24 hours ahead", C.pct(C.skill(long["y"], long["p_main"], long["p_climatology"])))
    c[3].metric("Telegram gain, next hour (quiet)", f"{h1.loc['quiet', 'gain'] * 100:+.1f} pts" if s.channels else "—",
                help="the Telegram model minus the alert-history model, at moments with no alert running")

    fig = go.Figure()
    for subset, color, label in (("all", C.BLUE, "all moments"), ("quiet", C.AQUA, "no alert running")):
        g = tab[tab["subset"] == subset]
        fig.add_trace(go.Scatter(x=g["h"], y=g["skill"], mode="lines+markers", name=label, marker=dict(size=6),
                                 line=dict(color=color, width=2.5), hovertemplate=label + ", %{x} h: %{y:.1%}<extra></extra>"))
    same = pred.merge(C.ref()["pred"][["t", "region", "h", "p_main"]], on=["t", "region", "h"], suffixes=("", "_ref"))
    if len(same):
        r = same.groupby("h").apply(lambda g: C.skill(g["y"], g["p_main_ref"], g["p_climatology"]), include_groups=False)
        fig.add_trace(go.Scatter(x=r.index, y=r.values, mode="lines", name="committed run, same forecasts",
                                 line=dict(color=C.GREY, width=1.5, dash="dash"),
                                 hovertemplate="committed run, %{x} h: %{y:.1%}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"))
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.25),
                      xaxis=dict(title="hours ahead", dtick=2), yaxis=dict(title="% better than the usual daily rhythm",
                                                                        tickformat=".0%"))
    C.show(fig)
    diff = float((same["p_main"] - same["p_main_ref"]).abs().max()) if len(same) else float("nan")
    match = (f"Recomputed here, {len(same):,} of them are also in the committed run: largest difference in a "
             f"probability {diff:.1e}" + (" (identical up to storage rounding)." if diff < 1e-6 else
                                          ", expected: the settings differ from the committed run."
                                          if s != P.Settings() else "."))
    st.caption(f"{len(pred):,} scored forecasts (region × hour × hours ahead). {match if len(same) else ''} The dashed "
               "line is the committed run on the same forecasts.")
    st.warning("Changing settings until these scores look good would be fitting to the test weeks. The committed "
               "model was chosen on the four validation weeks before them, and the test weeks were scored once.",
               icon="⚠️")


# ---------------------------------------------------------------- 6 forecast

def forecast():
    s, t = C.settings(), C.now()
    cfg = s.config()
    week = P.week_of(cfg, t)
    ready = C.has_models(s, week)
    clicked = C.stage_header("forecast", cheap=ready)
    st.markdown(f"**Forecast made at {C.kyiv(t)}** with the model for the week of {C.kyiv(week, '%d %b')}, trained on "
                f"the {s.train_days} days up to {C.kyiv(week - pd.Timedelta(days=1), '%d %b %H:%M')}.")
    ref = C.ref()
    pre = presets(ref["test"])
    st.caption("Jump the clock to an example moment from the test weeks (" + "; ".join(
        f"*{k}*: {v}" for k, v in PRESET_RULES.items()) + ").")
    cols = st.columns(len(pre))
    for col, (name, when) in zip(cols, pre.items()):
        col.button(name, on_click=C.set_now, args=(when,), use_container_width=True, key=f"jump_{name}")
    if clicked or (ready and C.status("forecast") != "done"):
        lines = []
        with st.status("Retraining for this week and forecasting…" if not ready else "Forecasting…", expanded=not ready):
            S.run_forecast(log=lambda m: (lines.append(m), st.write(m)))
        if not ready:
            st.session_state["log_forecast"] = lines
        st.rerun()  # redraw the status line above
    if st.session_state.get("log_forecast"):
        with st.expander("Log of the last retraining"):
            st.markdown("\n".join(f"- {m}" for m in st.session_state["log_forecast"]))
    if C.status("forecast") != "done":
        st.info(f"The clock is in the week of {C.kyiv(week, '%d %b')}; its model is not trained yet. Press **Run** "
                f"(about {10 * (2 if s.channels else 1)} s).")
        return
    out = C.runs()["forecast"]["out"]
    fc = out["fc"]

    a, b, c = st.columns([3, 2, 2], vertical_alignment="bottom")
    h = a.slider("Hours ahead", 1, 24, 1, help="1 = the hour right after the forecast is made.")
    rhythm = b.segmented_control("Colour the map by", ["Forecast", "Usual daily rhythm"], default="Forecast") == "Usual daily rhythm"
    hindsight = c.toggle("Show what happened", help="Hindsight: outcomes from after the replay moment, not known to "
                                                     "the model. Not available after the end of the data.")
    rows = fc[fc["h"] == h].sort_values("region")
    codes = [CODES[i] for i in rows["region"]]
    probs = rows["p_climatology" if rhythm else "p_main"].to_numpy()
    target = t + pd.Timedelta(hours=h - 1)
    H = S.hourly(C.LAST, s.max_alert_hours)  # full history, used only for hindsight
    actual = None
    if hindsight and target < C.LAST:
        actual = H.loc[target, codes].to_numpy()
    tail = (f"Actually under alert: **{int(np.nansum(actual))}** (red outline)." if actual is not None else
            "What happened is not known at this moment." if not hindsight else "No data for that hour yet.")
    st.markdown(f"For **{C.hour_span(target)}** ({h} h ahead): expected regions under alert **{probs.sum():.1f}** of 24. {tail}")
    C.show(C.ukraine_map(codes, probs, actual, "usual daily rhythm" if rhythm else "chance of an alert"))
    st.caption("Colour = chance of an alert in that hour. Grey = not forecast (Luhansk: permanent alert since 2022; "
               "Crimea: no data). 'Usual daily rhythm' shows how much of the map is simply each region's typical pattern.")

    names = [BY_CODE[c].name for c in CODES]
    r1, r2 = st.columns([1, 3], vertical_alignment="bottom")
    region = r1.selectbox("Region", names, index=CODES.index("UA-30"), key="fc_region")
    rc = names.index(region)
    r2.markdown(f"**{region}: the 24 hourly forecasts made at {C.kyiv(t)}** (shaded = the map hour)")
    one = fc[fc["region"] == rc].sort_values("h")
    starts = one["t"] + pd.to_timedelta(one["h"] - 1, unit="h")
    act = None
    if hindsight:
        act = np.array([H.at[x, CODES[rc]] if x < C.LAST else np.nan for x in starts])
    C.show(C.hourly_chart(starts, one["p_main"].to_numpy(), one["p_climatology"].to_numpy(), act, mark=target))

    so_far = out["so_far"]
    st.subheader(f"This week so far (since {C.kyiv(out['week'], '%a %d %b')})")
    if len(so_far):
        g1, gq = so_far[so_far["h"] == 1], so_far[(so_far["h"] == 1) & (so_far["active_now"] == 0)]
        c = st.columns(4)
        c[0].metric("Forecasts checked", f"{so_far['t'].nunique()} moments", f"{len(so_far):,} region-hours", delta_color="off")
        c[1].metric("Next hour", C.pct(C.skill(g1["y"], g1["p_main"], g1["p_climatology"])),
                    help="% better than the usual daily rhythm")
        c[2].metric("Next hour, no alert running", C.pct(C.skill(gq["y"], gq["p_main"], gq["p_climatology"])))
        c[3].metric("All 24 hours ahead", C.pct(C.skill(so_far["y"], so_far["p_main"], so_far["p_climatology"])))
        st.caption("Forecasts made since the model was last retrained whose 24 hours have all passed by now. Step the "
                   "clock forward to watch this fill up; at the start of a new week the model retrains.")
    else:
        st.caption("No forecast of this week has all its 24 hours behind it yet; move the clock at least a day past "
                   "the start of the week.")
    live = st.session_state.get("live")
    if t == C.LAST and live:
        n = sum(len(p) for p in live["posts"].values())
        st.info(f"{n} Telegram posts were fetched live (stage 1). They cannot move this forecast forward: it also needs "
                "to know which regions are under alert right now, and the alert history is published once a day "
                "(next update around 08:00 Kyiv).", icon="📡")


# ---------------------------------------------------------------- 7 result

def result():
    ref = C.ref()
    test, unc = ref["test"], ref["unc"]
    st.title("7 · Result")
    st.markdown("The conclusion of the committed run (`python -m airraid backtest`): the last four weeks of data "
                f"({C.kyiv(test['t'].min(), '%d %b')} – {C.kyiv(C.LAST, '%d %b %Y')}), each week forecast by a model "
                "trained only on earlier data. Scores compare the forecast with **the usual daily rhythm**: the share "
                "of hours with an alert in that region at that hour of day over the previous 28 days. Ranges are 95%, "
                "from resampling whole days.")
    nh, _, _ = C.ci(unc, "main_vs_climatology", "test", "all", 1)
    nq, nq_lo, nq_hi = C.ci(unc, "main_vs_climatology", "test", "quiet", 1)
    lg, lg_lo, lg_hi = C.ci(unc, "main_vs_climatology", "test", "all", "4-24")
    tg, tg_lo, tg_hi = C.ci(unc, "alertmap_minus_none", "test", "quiet", 1)
    tl = C.ci(unc, "alertmap_minus_none", "test", "quiet", "4-24")[0]
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown(f"#### Next hour: {C.pct(nh, 0)} better\nthan the usual daily rhythm, mostly because a running "
                    f"alert continues. With no alert running: **{C.pct(nq)}** ({C.pct(nq_lo)}–{C.pct(nq_hi)}).")
    with c2.container(border=True):
        st.markdown(f"#### 4–24 hours ahead: {C.pct(lg)} better\n({C.pct(lg_lo)}–{C.pct(lg_hi)}). Further ahead the "
                    "usual daily rhythm (busy front-line regions, busy hours) is hard to beat.")
    with c3.container(border=True):
        st.markdown(f"#### Telegram helps the first 1–3 hours\n**+{tg * 100:.1f} points** for the next hour with no "
                    f"alert running ({tg_lo * 100:+.1f} to {tg_hi * 100:+.1f}); from 4 hours on nothing measurable "
                    f"({tl * 100:+.1f}).")

    run = C.runs().get("model")
    if run is not None and len(run["out"]):
        pred = run["out"]
        tab = skill_table(pred)
        h1 = tab[tab["h"] == 1].set_index("subset")
        long = pred[pred["h"] >= 4]
        s = C.settings()
        st.info(f"**Your run (stage 5)**: {pred['t'].nunique()} forecast moments from {C.kyiv(pred['t'].min(), '%d %b')}, "
                f"{C.main_model_name(s)}, trained on {s.train_days} days, edited posts "
                f"{'left out' if s.exclude_edited else 'kept'}, alerts capped at {s.max_alert_hours:.0f} h.  \n"
                f"Next hour {C.pct(h1.loc['all', 'skill'])} · no alert running {C.pct(h1.loc['quiet', 'skill'])} · "
                f"4–24 h {C.pct(C.skill(long['y'], long['p_main'], long['p_climatology']))}"
                + (f" · Telegram gain {h1.loc['quiet', 'gain'] * 100:+.1f} pts" if s.channels else ""), icon="🔁")

    st.subheader("How good, hour by hour ahead")
    u = unc[(unc["metric"] == "main_vs_climatology") & (unc["period"] == "test")]
    fig = make_subplots(rows=1, cols=2, column_widths=[0.2, 0.8], horizontal_spacing=0.08,
                        subplot_titles=["Next hour", "2–24 hours ahead"])
    for subset, color, label in (("all", C.BLUE, "all moments"), ("quiet", C.AQUA, "no alert running at forecast time")):
        g = u[u["subset"] == subset]
        one = g[g["h"] == "1"]
        fig.add_trace(go.Scatter(x=[label], y=one["point"], mode="markers", marker=dict(color=color, size=11),
                                 error_y=dict(type="data", array=one["hi"] - one["point"], arrayminus=one["point"] - one["lo"]),
                                 showlegend=False, hovertemplate=label + ": %{y:.1%}<extra></extra>"), row=1, col=1)
        g = g[g["h"].str.isdigit()].assign(h=lambda d: d["h"].astype(int)).query("h >= 2").sort_values("h")
        fig.add_trace(go.Scatter(x=pd.concat([g["h"], g["h"][::-1]]), y=pd.concat([g["hi"], g["lo"][::-1]]), fill="toself",
                                 fillcolor=color, opacity=0.15, line=dict(width=0), hoverinfo="skip", showlegend=False),
                      row=1, col=2)
        fig.add_trace(go.Scatter(x=g["h"], y=g["point"], mode="lines", name=label, line=dict(color=color, width=2.5),
                                 hovertemplate=label + ", %{x} h: %{y:.1%}<extra></extra>"), row=1, col=2)
    fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"), row=1, col=2,
                  annotation_text="usual daily rhythm", annotation_position="bottom right")
    fig.update_yaxes(tickformat=".0%", row=1, col=1, rangemode="tozero")
    fig.update_yaxes(tickformat=".1%", row=1, col=2)
    fig.update_xaxes(title_text="hours ahead", dtick=2, row=1, col=2)
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=-0.25))
    C.show(fig)

    st.subheader("What Telegram adds")
    st.markdown("Gain over the same model without Telegram, at moments with no alert running (alert-map channel). "
                "The choice to use Telegram only up to 3 hours ahead was made on the validation weeks; the test weeks "
                "were then scored once.")
    fig = go.Figure()
    for period, color, dash in (("validation", C.GREY, "dash"), ("test", C.BLUE, "solid")):
        g = unc[(unc["metric"] == "alertmap_minus_none") & (unc["period"] == period) & (unc["subset"] == "quiet")]
        g = g[g["h"].str.isdigit()].assign(h=lambda d: d["h"].astype(int)).sort_values("h")
        fig.add_trace(go.Scatter(x=pd.concat([g["h"], g["h"][::-1]]), y=pd.concat([g["hi"], g["lo"][::-1]]), fill="toself",
                                 fillcolor=color, opacity=0.12, line=dict(width=0), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=g["h"], y=g["point"], mode="lines", name=f"{period} weeks",
                                 line=dict(color=color, width=2.5, dash=dash),
                                 hovertemplate=period + ", %{x} h: %{y:+.1%}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"))
    fig.add_vline(x=SHORT_HORIZON + 0.5, line=dict(color=C.GREY, width=1), annotation_text="Telegram used up to here",
                  annotation_position="top right")
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h", y=-0.3),
                      xaxis=dict(title="hours ahead", dtick=2), yaxis=dict(title="gain (points)", tickformat="+.1%"))
    C.show(fig)
    kp, kp_lo, kp_hi = C.ci(unc, "kpszsu_minus_none", "test", "quiet", 1)
    st.caption(f"The Air Force channel adds less: {kp * 100:+.1f} points for the next hour "
               f"(95%: {kp_lo * 100:+.1f} to {kp_hi * 100:+.1f}), so the main model uses only the alert-map channel.")

    st.subheader("If you acted on it: warnings vs false alarms")
    decision(test)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Are the probabilities honest?** When the forecast says 30%, an alert follows about 30% of the time.")
        fig = go.Figure([go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(color=C.GREY, dash="dot"), name="perfect")])
        for col, color, label in (("p_main", C.BLUE, "forecast"), ("p_climatology", C.GREY, "usual daily rhythm")):
            b = np.minimum((test[col] * 10).astype(int), 9)
            cal = test.groupby(b).agg(predicted=(col, "mean"), observed=("y", "mean"), n=("y", "size"))
            fig.add_trace(go.Scatter(x=cal["predicted"], y=cal["observed"], mode="lines+markers", name=label,
                                     line=dict(color=color, width=2.5 if col == "p_main" else 1.5), customdata=cal["n"],
                                     hovertemplate=label + ": said %{x:.0%} → happened %{y:.0%} (n=%{customdata})<extra></extra>"))
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.25),
                          xaxis=dict(title="forecast", tickformat=".0%", range=[0, 1], constrain="domain"),
                          yaxis=dict(title="share with an alert", tickformat=".0%", range=[0, 1], scaleanchor="x"))
        C.show(fig)
    with c2:
        st.markdown("**By region** (% better than the usual daily rhythm)")
        alerts = test[test["h"] == 1].groupby("region")["y"].mean()
        br = ref["by_region"]
        br = br[(br["model"] == "main") & br["region"].map(alerts).gt(0)].sort_values("brier_skill")
        none = [BY_CODE[CODES[i]].name for i in alerts[alerts == 0].index]
        fig = go.Figure(go.Bar(x=br["brier_skill"], y=br["region_name"], orientation="h",
                               marker_color=np.where(br["brier_skill"] > 0, C.BLUE, C.GREY),
                               hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(tickformat=".0%"))
        C.show(fig)
        if none:
            st.caption(f"Not shown: {', '.join(none)}, no alerts at all in the test weeks, so there is nothing to beat. "
                       "Grey bars: worse than the usual daily rhythm.")

    st.subheader("How it was tested, and its limits")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
**No look-ahead**
- Every forecast uses only data from before the moment it is made: alert history, and Telegram posts by publish time.
- Retrained weekly; each week is forecast by a model trained only on earlier weeks.
- The model was chosen on 4 validation weeks; the last 4 weeks (test) were scored once.
- Automated tests rebuild every input from data cut off at the forecast moment and require identical values, and
  check that the replay in this app reproduces the committed run.
- Edited Telegram posts are left out (their edit time is unknown); keeping them made the alert-map channel look better
  on validation (+3.2% instead of +2.7%).
""")
    with c2:
        st.markdown("""
**Limits**
- "Alert" means the volunteer record, which disagrees with the official one on 19% of oblast-hours.
- The data ends on 12 Oct 03:00 Kyiv; alerts still running when the snapshot was taken are missing from it.
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
    st.caption("Code and write-up: [github.com/LasonD/air-raids-analyzer](https://github.com/LasonD/air-raids-analyzer). "
               "Boundaries: geoBoundaries (UKR ADM1, © OpenStreetMap contributors, ODbL).")


def decision(test: pd.DataFrame):
    """Turn probabilities into a yes/no warning at a threshold and count what it catches."""
    q = test[(test["h"] == 1) & (test["active_now"] == 0)]
    days = q["t"].dt.floor("D").nunique()
    thr = st.slider("Warn a region when the chance of an alert starting in the next hour is at least", 0.05, 0.9, 0.3,
                    0.05, format="%.2f")
    rows = []
    n = int((q["p_main"] >= thr).sum())
    # Same number of warnings for both, so the rows compare which region-hours each one picks.
    for col, label in (("p_main", f"Forecast (chance ≥ {thr:.0%})"),
                       ("p_climatology", "Usual daily rhythm (its top picks, same number)")):
        warn = q[col].rank(method="first", ascending=False) <= n
        hit = (warn & (q["y"] == 1)).sum()
        rows.append({"warning based on": label, "new alerts caught": hit / max((q["y"] == 1).sum(), 1),
                     "warnings per day": warn.sum() / days, "false alarms per day": (warn & (q["y"] == 0)).sum() / days,
                     "warnings that came true": hit / max(warn.sum(), 1)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "new alerts caught": st.column_config.NumberColumn(format="percent"),
        "warnings that came true": st.column_config.NumberColumn(format="percent"),
        "warnings per day": st.column_config.NumberColumn(format="%.1f"),
        "false alarms per day": st.column_config.NumberColumn(format="%.1f")})
    st.caption(f"Test weeks, the next hour, moments with no alert running ({(q['y'] == 1).sum():,} new alerts in "
               f"{days} days across 24 regions). Both rows raise the same number of warnings, so the difference is "
               "how well each one chooses where. Lower the threshold to catch more alerts at the cost of more false alarms.")
