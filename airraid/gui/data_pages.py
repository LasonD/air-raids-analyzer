"""Overview and the data stages: sources, parsing, common format, patterns."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from airraid import pipeline as P
from airraid.gui import common as C
from airraid.gui import stages as S
from airraid.regions import BY_CODE, CODES, find_regions
from airraid.schema import KIND_GROUPS
from airraid.sources import github_csv
from airraid.sources.etryvoga import FILE as ALERT_FILE
from airraid.sources.telegram import classify, explain
from airraid.sources.telegram_parse import normalize

SHORT = {"sources": "alert history + 2 Telegram channels", "parsing": "posts → threat kind + regions",
         "format": "one format, hour by hour", "patterns": "what the history shows",
         "model": "weekly retraining, scored", "forecast": "24 regions × 24 hours ahead"}


# ---------------------------------------------------------------- overview

def overview():
    st.title("Air raid alerts in Ukraine: from raw data to a 24-hour forecast")
    st.markdown(
        "This app runs a forecasting pipeline step by step on real data. It reads the alert history and two "
        "Telegram channels, brings them into one format, learns from the past, and forecasts **for each of 24 "
        "regions the chance of an air raid alert in each of the next 24 hours**. Then it checks those forecasts "
        "against what actually happened.")
    st.info(f"**A research prototype, not a warning service.** The alert data ends {C.kyiv(C.LAST)} (Kyiv); the "
            "app replays the weeks before that. Always follow official air raid alerts.", icon="ℹ️")

    st.subheader("The pipeline")
    cols = st.columns(len(C.STAGES) + 1)
    for col, (key, (num, title, _)) in zip(cols, C.STAGES.items()):
        with col.container(border=True):
            st.markdown(f"**{num} · {title}**  \n{SHORT[key]}")
            r = C.runs().get(key)
            st.caption(C.BADGE[C.shown_status(key)] + (f" · {r['seconds']:.1f} s" if r else ""))
            st.page_link(C.PAGES[key], label="Open →")
    with cols[-1].container(border=True):
        st.markdown("**7 · Result**  \nhow good it is, what Telegram adds")
        st.caption("reads stages 5–6 and the committed run")
        st.page_link(C.PAGES["result"], label="Open →")

    a, b = st.columns([1, 3], vertical_alignment="center")
    if a.button("▶ Run all stages", type="primary", use_container_width=True):
        lines = []
        with st.status("Running the pipeline…", expanded=True):
            S.run_all(log=lambda m: (lines.append(m), st.write(m)))
        st.session_state["last_log"] = lines
        st.rerun()  # redraw the stage boxes above with their new status
    b.caption(f"For the current replay moment ({C.kyiv(C.now())}) and inputs. About 2–3 minutes the first time "
              "(most of it is training models); later runs reuse what is already computed.")
    if st.session_state.get("last_log"):
        with st.expander("Log of the last full run"):
            st.markdown("\n".join(f"- {m}" for m in st.session_state["last_log"]))

    st.subheader("How to use it")
    st.markdown(f"""
- **Replay clock** (left panel): the moment the app stands at, from {C.kyiv(C.FIRST, '%d %b')} to {C.kyiv(C.LAST, '%d %b')}.
  Every stage sees only what was published before it, so you can step forward and watch data arrive, the model retrain
  each week, and earlier forecasts get checked against what happened.
- **Inputs** (left panel): switch the Telegram channels on or off and change the model settings; the stages that depend
  on them are marked out of date.
- **Run**: every stage has a Run button. Data stages take seconds and then follow the clock; model stages train
  gradient-boosting models (about 10 s per model and week) and wait for a click.
- **Live data**: stages 1 and 2 can fetch the newest Telegram posts right now and parse them. They cannot change a
  forecast yet: a forecast also needs the alert history up to the same moment, and that is published once a day.
""")
    st.subheader("Where it ends up")
    unc = C.ref()["unc"]
    nh = C.ci(unc, "main_vs_climatology", "test", "all", 1)[0]
    lg = C.ci(unc, "main_vs_climatology", "test", "all", "4-24")[0]
    tg = C.ci(unc, "alertmap_minus_none", "test", "quiet", 1)[0]
    st.markdown(f"On the last four weeks the forecast is **{C.pct(nh, 0)} better than each region's usual daily rhythm "
                f"for the next hour**, but only **{C.pct(lg)} better 4–24 hours ahead**. The alert-map Telegram channel "
                f"adds **{tg * 100:+.1f} points** for the next hour when no alert is running. Details: ")
    st.page_link(C.PAGES["result"], label="7 · Result")


# ---------------------------------------------------------------- 1 sources

@st.cache_data(show_spinner=False)
def daily_counts() -> pd.DataFrame:
    inp = C.inputs()
    a = inp.alerts.frame
    out = {"alerts started (eTryvoga)": a.groupby(a["start_utc"].dt.floor("D")).size()}
    for s in inp.signals:
        f = s.frame.drop_duplicates(["ref", "published_at_utc"])
        out[f"posts kept ({C.CHANNELS[s.name]})"] = f.groupby(f["published_at_utc"].dt.floor("D")).size()
    df = pd.DataFrame(out).fillna(0)
    return df[df.index >= pd.Timestamp("2026-01-01", tz="UTC")]


@st.cache_data(show_spinner=False)
def raw_alert_rows() -> pd.DataFrame:
    return pd.read_csv(github_csv.fetch(ALERT_FILE), parse_dates=["started_at", "finished_at"])


def source_cards():
    h = C.ref()["health"]
    e, k, m = h.get("etryvoga", {}), h.get("kpszsu", {}), h.get("povitryanatrivogaaa", {})
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown(
            "**Target: the alert history**  \n"
            "Oblast-level air raid alerts recorded by the volunteer eTryvoga channel, via the open "
            "[ukrainian-air-raid-sirens-dataset](https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset) "
            f"(fixed version {github_csv.PINNED_SHA[:7]}). Feb 2022 – 12 Oct 2026, {e.get('records', 0):,} alerts. "
            "Updated once a day.")
    with c2.container(border=True):
        st.markdown(
            "**Input: Air Force of Ukraine, [@kpszsu](https://t.me/s/kpszsu)**  \n"
            f"Official live threat tracks (drones, missiles, guided bombs) by region. {k.get('records', 0):,} posts "
            "since 1 Jan 2026, read from the public web preview.")
    with c3.container(border=True):
        st.markdown(
            "**Input: alert-map channel, [@povitryanatrivogaaa](https://t.me/s/povitryanatrivogaaa)**  \n"
            f"Volunteer drone routes, missile tracks, explosions. {m.get('records', 0):,} posts since 1 Jan 2026, "
            "read from the public web preview.")


def live_block(key: str):
    """Fetch the newest Telegram posts right now; shared by stages 1 and 2."""
    live = st.session_state.get("live")
    a, b = st.columns([1, 3], vertical_alignment="center")
    if a.button("Fetch the newest posts now", key=f"live_{key}", use_container_width=True):
        try:
            with st.spinner("Asking t.me …"):
                S.fetch_live()
            live = st.session_state["live"]
        except Exception as exc:  # network trouble must not break the page
            st.error(f"Could not reach Telegram: {exc}")
    if live:
        newest = max(p["published_at_utc"].max() for p in live["posts"].values())
        b.markdown(f"Fetched at **{C.kyiv(live['at'], '%H:%M:%S')}** (Kyiv): {sum(map(len, live['posts'].values()))} "
                   f"posts, the newest from **{C.kyiv(newest, '%H:%M')}**, "
                   f"{(live['at'] - newest).total_seconds() / 60:.0f} min before fetching.")
    else:
        b.caption("Reads the newest page of each channel straight from Telegram (about 20 posts each).")
    return live


def sources():
    if C.stage_header("sources", cheap=True):
        with st.spinner("Loading the alert history and both channels…"):
            S.run_sources(log=lambda *_: None)
        st.rerun()  # redraw the status line above
    source_cards()
    if C.status("sources") == "not run":
        st.info("Press **Run** to load the data (about 10–20 s the first time).")
        return
    t, inp = C.now(), C.inputs()
    st.subheader(f"What has arrived by {C.kyiv(t)}")
    cols = st.columns(3)
    known = P.known_at(inp, t)
    for col, src in zip(cols, [known.alerts, *known.signals]):
        f = src.frame
        when = f["start_utc"].max() if src.role == "alerts" else f["published_at_utc"].max()
        label = "eTryvoga alerts" if src.role == "alerts" else C.CHANNELS[src.name]
        col.metric(label, f"{len(f):,} rows", f"latest {C.kyiv(when, '%d %b %H:%M')}", delta_color="off")

    d = daily_counts()
    d = d[d.index < t]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.1, subplot_titles=list(d.columns))
    for i, col in enumerate(d.columns, start=1):
        fig.add_trace(go.Bar(x=C.local(d.index), y=d[col], marker_color=C.BLUE if i > 1 else C.ALERT_RED,
                             showlegend=False, hovertemplate="%{x|%d %b}: %{y}<extra></extra>"), row=i, col=1)
    if t < C.LAST:
        fig.add_vrect(x0=C.local(t), x1=C.local(C.LAST) + pd.Timedelta(hours=12), fillcolor=C.GREY, opacity=0.12,
                      line_width=0)
        fig.add_annotation(x=C.local(t), y=1, yref="paper", text=" not arrived yet", showarrow=False, xanchor="left",
                           yanchor="bottom", font=dict(color=C.GREY, size=11))
    fig.update_xaxes(range=[pd.Timestamp("2026-01-01"), C.local(C.LAST) + pd.Timedelta(days=1)])
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=30, b=10), bargap=0.1)
    st.markdown("**Records per day, 2026.** Telegram posts count once per post; dips are gaps in the source, which "
                "the pipeline treats as *unknown*, not as quiet.")
    C.show(fig)

    st.subheader("Raw data, as it comes in")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Alert history**: rows of the CSV file, before any processing")
        raw = raw_alert_rows()
        st.dataframe(raw[raw["started_at"] < t].tail(8), hide_index=True)
    with c2:
        st.markdown("**Telegram**: posts as published (newest before the replay moment)")
        posts = C.classified("povitryanatrivogaaa")
        if posts is None:
            st.caption("Post texts are not part of the repository (`python -m airraid fetch` downloads them); "
                       "the live fetch below shows real posts.")
        else:
            p = posts[posts["published_at_utc"] < t].tail(8)
            st.dataframe(pd.DataFrame({"published (Kyiv)": p["published_at_utc"].dt.tz_convert(C.KYIV).dt.strftime("%d %b %H:%M"),
                                       "text": p["text"]}), hide_index=True)

    st.subheader("Live: the newest posts right now")
    live = live_block("sources")
    if live:
        rows = pd.concat([p.assign(channel=C.CHANNELS[ch]) for ch, p in live["posts"].items()])
        rows = rows.sort_values("published_at_utc", ascending=False)
        st.dataframe(pd.DataFrame({"published (Kyiv)": rows["published_at_utc"].dt.tz_convert(C.KYIV).dt.strftime("%d %b %H:%M"),
                                   "channel": rows["channel"], "text": rows["text"]}), hide_index=True, height=260)
        st.caption(f"These arrived after the alert data ends ({C.kyiv(C.LAST)}). Stage 2 parses them; they cannot "
                   "enter a forecast until the alert history for the same hours is published.")


# ---------------------------------------------------------------- 2 parsing

EXAMPLES = {
    ("povitryanatrivogaaa", "Drone routes"): "✈️Київщина: →Богуслав/Тараща з Черкащини. ✈️Чернігівщина: →Ріпки/Славутич/Київщина (2х). ✈️Одещина: →Білгород-Дністровський/р-н з моря.",
    ("povitryanatrivogaaa", "Explosions"): "💥Макарів/околиці (Київщина) - вибухи",
    ("povitryanatrivogaaa", "Guided bombs, town not known"): "КАБ🚀→Б-Дністровський/р-н\nКАБ🚀→Маяки",
    ("kpszsu", "Missile"): "🚀 Ракета на Дніпропетровщині, повз Кривий Ріг курс північно-західний",
    ("kpszsu", "All clear"): "📢 Відбій загрози застосування балістичного озброєння.",
    ("kpszsu", "Short follow-up"): "Маяки терміново в укриття",
}


def playground():
    st.subheader("Try the parser")
    st.caption("Real posts from October 2026, or type your own. The same rules run on every downloaded post.")
    pick = st.pills("Example", [f"{C.CHANNELS[ch]}: {name}" for ch, name in EXAMPLES], default=None,
                    label_visibility="collapsed")
    if pick and pick != st.session_state.get("pg_pick"):  # load an example once, then let the user edit it
        ch, name = next(k for k in EXAMPLES if f"{C.CHANNELS[k[0]]}: {k[1]}" == pick)
        st.session_state["pg_text"], st.session_state["pg_channel"] = EXAMPLES[(ch, name)], ch
    st.session_state["pg_pick"] = pick
    st.session_state.setdefault("pg_text", next(iter(EXAMPLES.values())))
    st.session_state.setdefault("pg_channel", "povitryanatrivogaaa")
    a, b = st.columns([3, 2])
    text = a.text_area("Post text", key="pg_text", height=120)
    channel = b.selectbox("Channel rules", list(C.CHANNELS), key="pg_channel", format_func=C.CHANNELS.get)
    clean = normalize(text)
    kind = classify(clean, channel)
    regions = find_regions(clean)
    with b.container(border=True):
        st.markdown(f"**Kind:** {kind if kind not in ('drop', 'follow_up') else '—'}  \n"
                    f"**Why:** {explain(clean, channel)}  \n"
                    f"**Regions:** {', '.join(BY_CODE[r].name for r in regions) or 'none recognised'}")
    st.caption("Kinds feed the model in five groups: drones, missiles, aviation (incl. guided bombs), explosions, all-clear. "
               "Place names are matched with Ukrainian case endings (Київщина, Київщини, Київщині…); towns not in the "
               "list, like Маяки, are missed.")


def parsing():
    if C.stage_header("parsing", cheap=True):
        with st.spinner("Parsing every downloaded post…"):
            S.run_parsing(log=lambda *_: None)
        st.rerun()  # redraw the status line above
    playground()
    if C.status("parsing") == "not run":
        st.info("Press **Run** to parse all downloaded posts.")
        return
    t = C.now()
    st.subheader("All posts, parsed")
    rows = []
    for ch in P.SIGNALS:
        p = C.classified(ch)
        if p is None:
            continue
        threat = ~p["kind"].isin(["drop", "follow_up", "clear"])
        rows.append({"channel": C.CHANNELS[ch], "posts": len(p), "kept as events": int((p["kind"] != "drop").sum()),
                     "threat posts naming a region": (p.loc[threat, "regions"].str.len() > 0).mean(),
                     "edited later (left out)": p["edited"].mean()})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
            c: st.column_config.NumberColumn(format="percent") for c in ("threat posts naming a region", "edited later (left out)")})
        st.caption("Edited posts are left out: Telegram shows when a post was published, not when it was edited, and "
                   "the alert-map channel updates route summaries in place, so the text may describe later events. "
                   "Known flaw: a post with no threat word that names a place within an hour of a threat post is taken "
                   "as its follow-up (meant for 'На Боярку'); this also catches some news posts (about 50 of 78,000 "
                   "events, e.g. casualty reports, or a cadet ceremony in Kharkiv seen in the live posts).")
        ch = st.segmented_control("Channel", list(C.CHANNELS), default="povitryanatrivogaaa", format_func=C.CHANNELS.get,
                                  key="parse_channel") or "povitryanatrivogaaa"
        p = C.classified(ch)
        p = p[p["published_at_utc"] < t].tail(25).iloc[::-1]
        st.dataframe(pd.DataFrame({
            "published (Kyiv)": p["published_at_utc"].dt.tz_convert(C.KYIV).dt.strftime("%d %b %H:%M"),
            "kind": p["kind"].replace({"drop": "— dropped"}),
            "regions": p["regions"].map(lambda r: ", ".join(BY_CODE[c].name for c in r)),
            "text": p["text"]}), hide_index=True, height=360)
        st.caption(f"The 25 newest posts before the replay moment ({C.kyiv(t)}).")
    else:
        st.caption("Post texts are not part of the repository; the committed snapshot holds the parsed events only. "
                   "`python -m airraid fetch` downloads the posts; the live fetch below parses real posts now.")

    st.subheader("Live: parse the newest posts right now")
    live = live_block("parsing")
    if live:
        rows = pd.concat([p.assign(channel=C.CHANNELS[ch]) for ch, p in live["posts"].items()])
        rows = rows.sort_values("published_at_utc", ascending=False)
        st.dataframe(pd.DataFrame({
            "published (Kyiv)": rows["published_at_utc"].dt.tz_convert(C.KYIV).dt.strftime("%d %b %H:%M"),
            "channel": rows["channel"], "kind": rows["kind"].replace({"drop": "— dropped"}),
            "regions": rows["regions"].map(lambda r: ", ".join(BY_CODE[c].name for c in r)),
            "text": rows["text"]}), hide_index=True, height=300)


# ---------------------------------------------------------------- 3 common format

def timeline(region: str, start: pd.Timestamp, end: pd.Timestamp):
    """Alerts and Telegram events for one region on one time axis, cut at the replay moment."""
    inp = P.known_at(C.inputs(), end)
    fig = go.Figure()
    a = inp.alerts.frame
    a = a[(a["region"] == region) & (a["end_utc"] > start)]
    for _, r in a.iterrows():
        x1 = min(r["end_utc"], end)
        fig.add_trace(go.Scatter(x=[C.local(r["start_utc"]), C.local(x1)], y=["alerts"] * 2,
                                 mode="lines", line=dict(color=C.ALERT_RED, width=14), showlegend=False,
                                 hovertemplate=f"alert {C.kyiv(r['start_utc'], '%H:%M')}–"
                                               f"{'still running' if r['end_utc'] > end else C.kyiv(r['end_utc'], '%H:%M')}<extra></extra>"))
    seen = set()
    for src in inp.signals:
        f = src.frame
        f = f[(f["region"] == region) & (f["published_at_utc"] >= start)]
        if C.settings().exclude_edited:
            f = f[~f["edited"]]
        for group, g in f.groupby(f["kind"].map(KIND_GROUPS)):
            fig.add_trace(go.Scatter(x=C.local(g["published_at_utc"]), y=[C.CHANNELS[src.name]] * len(g),
                                     mode="markers", marker=dict(size=10, color=C.KIND_COLORS[group], symbol="circle"),
                                     name=group, legendgroup=group, showlegend=group not in seen,
                                     hovertemplate=f"%{{x|%H:%M}} {group}<extra></extra>"))
            seen.add(group)
    C.now_line(fig, end)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=-0.25),
                      xaxis=dict(range=[C.local(start), C.local(end) + pd.Timedelta(hours=1)]),
                      yaxis=dict(categoryorder="array", categoryarray=[C.CHANNELS["kpszsu"], C.CHANNELS["povitryanatrivogaaa"], "alerts"]))
    return fig


def common_format():
    if C.stage_header("format", cheap=True):
        with st.spinner("Normalising and building the hourly table…"):
            S.run_format(log=lambda *_: None)
        st.rerun()  # redraw the status line above
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Alerts**, one row per alert")
        st.dataframe(pd.DataFrame({"column": ["region", "start_utc", "end_utc", "end_estimated"],
                                   "meaning": ["ISO 3166-2 code (UA-63 = Kharkiv)", "alert start, UTC",
                                               "all-clear, UTC", "end time was guessed by the source"]}), hide_index=True)
    with c2:
        st.markdown("**Signals**, one row per post and region it names")
        st.dataframe(pd.DataFrame({"column": ["published_at_utc", "region", "kind", "ref", "edited"],
                                   "meaning": ["publish time, UTC", "region code, or empty for countrywide posts",
                                               "drone, missile, ballistic, guided_bomb, aviation, explosion, clear",
                                               "post id", "edited after publishing"]}), hide_index=True)
    st.caption("Every source adapter outputs this format and reports the period it covers; the rest of the pipeline "
               "never sees anything source-specific. A gap in a source becomes *unknown*, never *quiet*.")
    if C.status("format") == "not run":
        st.info("Press **Run** to bring the sources into this format.")
        return
    t, inp = C.now(), C.inputs()
    st.markdown("**Checks passed** (`schema.validate`): " + " · ".join(
        f"✓ {src.name}: {len(src.frame):,} rows, covered {src.covered_from:%d %b %Y} – {src.covered_to:%d %b %Y %H:%M} UTC"
        for src in [inp.alerts, *inp.signals]))

    st.subheader("One region, all sources on one time axis")
    names = [BY_CODE[c].name for c in CODES]
    a, b = st.columns([2, 1])
    region = a.selectbox("Region", names, index=CODES.index("UA-63"), key="fmt_region")
    hours = b.segmented_control("Window", [12, 24, 48], default=24, format_func=lambda h: f"last {h} h",
                                key="fmt_hours") or 24
    show_fig = timeline(CODES[names.index(region)], t - pd.Timedelta(hours=hours), t)
    C.show(show_fig)
    st.caption("Red bars: alerts in the target data. Dots: Telegram events naming this region, coloured by kind. "
               "Nothing after the replay moment exists yet for the app.")

    st.subheader("What the model receives: the hourly table")
    H = S.hourly(t, C.settings().max_alert_hours)
    last = H[H.index >= t - pd.Timedelta(hours=48)]
    order = last.mean().sort_values().index
    fig = go.Figure(go.Heatmap(z=last[order].T.values, x=C.local(last.index), y=[BY_CODE[c].name for c in order],
                               zmin=0, zmax=1, colorscale=[[0, C.theme()["ramp"][0]], [1, C.ALERT_RED]], showscale=False,
                               xgap=1, ygap=1, hovertemplate="%{y}, %{x|%d %b %H:00}: %{z:.0f}<extra></extra>"))
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10))
    C.show(fig)
    st.caption(f"Alerts capped at {C.settings().max_alert_hours:.0f} h (longer ones are almost always a missed "
               "all-clear), then turned into 1 = alert in that hour. Together with the Telegram events this table is "
               "all the model gets.")
    with st.expander("Why the volunteer record and not the official one"):
        ag = C.ref()["agreement"].rename(columns={"region": "Region", "official_alert_hours": "Official: share of hours",
                                                   "volunteer_alert_hours": "Volunteer: share of hours",
                                                   "agreement": "Hours agreeing"})
        st.markdown("The official record stops on 7 Sep 2026, and since December 2025 alerts are declared per district, "
                    "so the two disagree on 19% of oblast-hours (Donetsk: official 99.8% of hours, volunteer 28%). The "
                    "volunteer record is complete up to 12 Oct and stays at oblast level.")
        st.dataframe(ag, hide_index=True, column_config={c: st.column_config.NumberColumn(format="percent")
                                                         for c in ag.columns if c != "Region"})
        st.caption("1 Jun – 7 Sep 2026; official = any district of the oblast under alert.")


# ---------------------------------------------------------------- 4 patterns

def patterns():
    if C.stage_header("patterns", cheap=True):
        with st.spinner("Computing patterns…"):
            S.run_patterns(log=lambda *_: None)
        st.rerun()  # redraw the status line above
    if C.status("patterns") == "not run":
        st.info("Press **Run** to analyse the alert history known at the replay moment.")
        return
    t = C.now()
    R = S.patterns(t, C.settings().max_alert_hours)
    st.caption(f"From the alert history known at {C.kyiv(t)}; 'recent' = the 26 weeks before it (the model's training window).")

    st.subheader("1. Four and a half years of alerts")
    m = R["monthly"]
    fig = go.Figure(go.Scatter(x=C.local(m.index), y=m.values, mode="lines", line=dict(color=C.BLUE, width=2),
                               hovertemplate="%{x|%b %Y}: %{y:.0%}<extra></extra>"))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis=dict(tickformat=".0%", rangemode="tozero", title="region-hours under alert"))
    C.show(fig)
    st.caption(f"Share of region-hours under alert per month. Peak {m.idxmax():%b %Y} ({C.pct(m.max(), 0)}), lowest "
               f"{m.idxmin():%b %Y} ({C.pct(m.min(), 0)}). **For the model:** the level drifts over months, so it trains "
               "on a rolling half-year and compares against the last 28 days, not against all history.")

    st.subheader("2. Hour of day, region by region")
    prof = R["rhythm"]
    by_hour = prof.mean()
    prof.index = [BY_CODE[c].name for c in prof.index]
    prof = prof.loc[prof.mean(axis=1).sort_values().index]
    fig = go.Figure(go.Heatmap(z=prof.values, x=prof.columns, y=prof.index, zmin=0, zmax=1, xgap=2, ygap=2,
                               colorscale=C.ramp(), colorbar=dict(tickformat=".0%", thickness=10),
                               hovertemplate="%{y}, %{x}:00 → %{z:.0%}<extra></extra>"))
    fig.update_layout(height=540, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(title="hour of day (Kyiv)", dtick=2))
    C.show(fig)
    wd = R["weekday"]
    st.caption("Share of hours under alert by region and hour of day (recent). Region matters far more than the hour: "
               f"across all regions the busiest hour is {by_hour.idxmax():02d}:00 ({C.pct(by_hour.max(), 0)}), the "
               f"quietest {by_hour.idxmin():02d}:00 ({C.pct(by_hour.min(), 0)}); by day of week it varies only "
               f"{C.pct(wd.min(), 0)}–{C.pct(wd.max(), 0)}. **For the model:** this pattern is the baseline it has to "
               "beat (the 'usual daily rhythm'); region and hour of day are features, the day of week matters little.")

    st.subheader("3. An alert now says a lot about the next hour, little about later")
    pe = R["persistence"]
    fig = go.Figure()
    for col, color, label in (("after_alert", C.ALERT_RED, "after an hour with an alert"),
                              ("after_quiet", C.BLUE, "after a quiet hour")):
        fig.add_trace(go.Scatter(x=pe["h"], y=pe[col], mode="lines+markers", name=label, marker=dict(size=6),
                                 line=dict(color=color, width=2.5),
                                 hovertemplate=label + ", %{x} h later: %{y:+.0%}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"), annotation_text="the region's usual level",
                  annotation_position="top right")
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.25),
                      xaxis=dict(title="hours later", dtick=2),
                      yaxis=dict(title="chance of an alert vs usual (points)", tickformat="+.0%"))
    C.show(fig)
    pa = pe.set_index("h")["after_alert"]
    st.caption(f"Compared with each region's own usual level (recent, averaged over regions): after an hour with an "
               f"alert, the next hour is **{pa[1] * 100:+.0f} points** more likely to have one; 2 hours later "
               f"{pa[2] * 100:+.0f}, 12 hours later {pa[12] * 100:+.0f}. **For the model:** this is why the next hour is "
               "easy and 4–24 hours ahead is hard, whatever the model.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("4. How long alerts last")
        d = R["durations"]
        fig = go.Figure(go.Histogram(x=d.clip(upper=24), xbins=dict(start=0, end=24.5, size=0.5), marker_color=C.BLUE,
                                     hovertemplate="%{x} h: %{y} alerts<extra></extra>"))
        fig.add_vline(x=C.settings().max_alert_hours, line=dict(color=C.GREY, dash="dot"),
                      annotation_text="cap", annotation_position="top right")
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(title="hours (24 = 24 or more)"),
                          yaxis=dict(title="alerts"))
        C.show(fig)
        st.caption(f"Recent alerts: median {d.median() * 60:.0f} min, {C.pct((d > 12).mean())} longer than 12 h. "
                   "**For the model:** such long ones are treated as a missed all-clear and capped.")
    with c2:
        st.subheader("5. Regions go under alert together")
        tg = R["together"]
        fig = go.Figure(go.Bar(x=tg.index, y=tg.values, marker_color=C.BLUE,
                               hovertemplate="%{x} regions at once: %{y:.0%} of hours<extra></extra>"))
        fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis=dict(title="regions under alert in the same hour"), yaxis=dict(tickformat=".0%"))
        C.show(fig)
        st.caption(f"Hour-by-hour correlation: {R['nb_corr']:.2f} between neighbouring regions, {R['other_corr']:.2f} "
                   "between others. **For the model:** what neighbours and the whole country are doing right now is a feature.")
