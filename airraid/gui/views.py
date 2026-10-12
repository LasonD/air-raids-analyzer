"""The app: a top bar, the pipeline strip and one view per stage. A run draws its view as it computes."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from airraid import pipeline as P
from airraid.backtest import SHORT_HORIZON
from airraid.gui import common as C
from airraid.gui import stages as S
from airraid.regions import BY_CODE, CODES, find_regions
from airraid.schema import KIND_GROUPS
from airraid.sources import github_csv, registry
from airraid.sources.etryvoga import FILE as ALERT_FILE
from airraid.sources.telegram import classify, explain, resolve_follow_ups
from airraid.sources.telegram_parse import load_posts, normalize

ORDER = list(C.STAGES)
STRIP: dict = {}  # stage -> status slot in the pipeline strip, filled live during runs

CSS = """<style>
[data-testid="stMainBlockContainer"], .block-container {padding-top: 4.2rem; padding-bottom: 2rem;}
.arrow {text-align: center; font-size: 1.5rem; color: #8a8985; line-height: 1;}
.st-key-strip [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important;}
.st-key-strip [data-testid="stColumn"] {min-width: 0 !important;}
[class*="st-key-nodebox_"] {padding: 0.55rem 0.5rem 0.85rem !important; gap: 0.45rem !important; min-width: 0;}
[class*="st-key-nodebox_"] [data-testid="stMarkdownContainer"] {width: 100%; margin: 0; padding: 0;}
[class*="st-key-nodebox_"] button {padding: 0.3rem 0.2rem; min-height: 2.2rem; min-width: 0; max-width: 100%;}
[class*="st-key-nodebox_"] button div, [class*="st-key-nodebox_"] button p {min-width: 0; max-width: 100%;}
[class*="st-key-nodebox_"] button p {font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.st-key-topbar [data-testid="stColumn"] {min-width: 0 !important;}
.st-key-topbar button {padding-left: 0.3rem; padding-right: 0.3rem;}
</style>"""

ABOUT = {
    "sources": """
- **Alert history** (what is forecast): oblast-level alerts from the volunteer eTryvoga channel, via the open
  [ukrainian-air-raid-sirens-dataset](https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset) (pinned
  version `d10c80f`), Feb 2022 – 12 Oct 2026. Published once a day.
- **Air Force** [@kpszsu](https://t.me/s/kpszsu): official threat tracks by region, since 1 Jan 2026.
- **Alert map** [@povitryanatrivogaaa](https://t.me/s/povitryanatrivogaaa): volunteer drone routes, missile
  tracks, explosions, since 1 Jan 2026.
- Telegram is read from the public web preview. A gap in a source counts as *unknown*, never as quiet.
- **📡 Newest posts** reads both channels right now. They cannot enter a forecast until the alert history for
  the same hours is published.""",
    "parsing": """
- Ordered keyword and emoji rules per channel decide the kind; the first match wins.
- Place names are matched with Ukrainian case endings (Київщина, Київщини, Київщині…) plus frequent towns.
- A post with no threat word that names a place within an hour of a threat post continues it ("На Боярку").
  Known flaw: some news posts get caught too (about 50 of 78,000 events).
- Edited posts are left out: Telegram shows the publish time but the latest text.
- Post texts are not in the repository; without `python -m airraid fetch` only live posts are parsed.""",
    "format": """
- **Alerts**: region, start, end. **Signals**: publish time, region (or none), kind, post id, edited.
- Every source adapter outputs this; the rest of the pipeline never sees a source name.
- Each source reports the period it covers, so a gap becomes unknown, not quiet.
- Alerts longer than the cap (12 h by default) are cut: almost always a missed all-clear.
- The hourly table plus the Telegram events is everything the model gets.
- Why the volunteer record: the official one stops on 7 Sep 2026 and is per district since December 2025;
  the two disagree on 19% of oblast-hours.""",
    "patterns": """
- Everything here comes from the alert history known at "now".
- "Recent" = the 26 weeks before "now", the model's training window.
- Each chart title says what it means for the model; hover for the numbers.""",
    "model": """
- Gradient boosting; Telegram features for 1–3 h ahead, alert history only after (chosen on the validation weeks).
- Each week's model is trained on the days before it, never on the week it forecasts; inputs are cut at each
  forecast moment (checked by automated tests).
- A forecast is scored once all its 24 hours have passed.
- **% better** = Brier skill against the usual daily rhythm (the region's alert share at that hour over the
  previous 28 days). 0% = no better than that rhythm.
- With the committed settings this reproduces `results/predictions.parquet`.
- Tuning settings until these scores look good would be fitting to the test weeks; the committed choice was made
  on the four validation weeks before them.""",
    "forecast": """
- The chance of an alert in each region for each of the next 24 hours, made at "now" with that week's model.
- **Show what happened** reveals outcomes after "now" (hindsight; never seen by the model).
- **▷ Play** steps the clock an hour at a time; at a new week the model retrains first.
- Grey regions are not forecast (Luhansk: permanent alert since 2022; Crimea: no data).""",
    "result": """
- From the committed run (`python -m airraid backtest`): the last four weeks, 14 Sep – 12 Oct 2026, each week
  forecast by a model trained only on earlier data. Ranges are 95%, from resampling whole days.
- **% better**: Brier skill score against the usual daily rhythm. **No alert running**: moments when the region
  had no alert at forecast time, i.e. "will a new one start?".
- Zakarpattia is left out of the region chart: it had no alerts in the test weeks, so there is nothing to beat.
- Limits: the target is one volunteer record; beyond a few hours the forecast stays close to the usual daily
  rhythm; Ivano-Frankivsk and Chernihiv were worse than it in the test weeks; live posts cannot be used yet.""",
}


# ---------------------------------------------------------------- top bar and strip

def _clock_from_widgets():
    day, hour = st.session_state["clock_day"], st.session_state["clock_hour"]
    C.set_now(pd.Timestamp(day).replace(hour=hour).tz_localize(C.KYIV).tz_convert("UTC"))


def _step(hours: int):
    C.set_now(C.now() + pd.Timedelta(hours=hours))


def _reset():
    for k, v in C.DEFAULTS.items():
        st.session_state[k] = v


def top_bar() -> dict:
    for k, v in C.DEFAULTS.items():
        st.session_state.setdefault(k, v)
    local = C.now().tz_convert(C.KYIV)
    st.session_state["clock_day"], st.session_state["clock_hour"] = local.date(), local.hour  # before the widgets

    a, b = st.columns([3, 2], vertical_alignment="bottom")
    a.markdown("#### Air raid alerts in Ukraine · 24-hour forecast pipeline")
    b.caption(f"Research prototype, not a warning service · data until {C.kyiv(C.LAST)} Kyiv",
              help="A replay of the last eight weeks of real data. Always follow official air raid alerts.")
    c = st.container(key="topbar").columns([1.75, 1.35, 0.7, 0.7, 0.7, 0.7, 1.3, 1.3, 1.35],
                                            vertical_alignment="bottom")
    c[0].date_input("Now (Kyiv)", key="clock_day", min_value=C.FIRST.tz_convert(C.KYIV).date(),
                    max_value=C.LAST.tz_convert(C.KYIV).date(), on_change=_clock_from_widgets, format="DD.MM.YYYY",
                    help="The replay clock: every stage sees only what was published before this moment.")
    c[1].selectbox("Hour", list(range(24)), key="clock_hour", format_func=lambda h: f"{h:02d}:00",
                   on_change=_clock_from_widgets)
    for col, (label, hours) in zip(c[2:6], (("−1d", -24), ("−1h", -1), ("+1h", 1), ("+1d", 24))):
        col.button(label, on_click=_step, args=(hours,), use_container_width=True, key=f"step_{hours}",
                   help=f"Move the clock {'back' if hours < 0 else 'forward'} {abs(hours) // 24 or abs(hours)} "
                        f"{'day' if abs(hours) == 24 else 'hour'}")
    play = c[6].button("▷ Play", use_container_width=True,
                       help="Step the clock an hour at a time for a day and watch the forecast update. Any click stops it.")
    changed = C.settings() != P.Settings() or st.session_state.get("n_weeks") != C.DEFAULTS["n_weeks"]
    with c[7].popover("⚙ Changed" if changed else "⚙ Inputs", use_container_width=True,
                      help="Inputs differ from the committed run" if changed else "Telegram channels and model settings"):
        st.caption("The alert history is always used: it is what is forecast.")
        for ch, name in C.CHANNELS.items():
            st.toggle(f"{name.capitalize()} (@{ch})", key=f"ch_{ch}")
        st.select_slider("Training window (days)", [56, 91, 126, 182], key="train_days")
        st.select_slider("Cap alerts at (hours)", [6, 12, 24], key="max_alert_hours")
        st.checkbox("Leave out edited Telegram posts", key="exclude_edited")
        st.slider("Weeks to score", 1, 8, key="n_weeks")
        st.button("Reset to the committed settings", on_click=_reset, use_container_width=True)
    run_all = c[8].button("▶ Run all", type="primary", use_container_width=True,
                          help="Run every stage in order for this moment and these inputs, watching each one fill.")
    return {"play": play, "run_all": run_all}


STATE_COLOR = {"not run": "#a3a29e", "running": C.BLUE, "done": C.AQUA, "out of date": "#e07b1a", "result": C.GREY}
def node_status(stage: str, text: str | None = None, state: str | None = None) -> None:
    if text is None:
        r = C.runs().get(stage)
        if stage == "result":
            state, text = "result", "● committed run"
        else:
            state = C.status(stage)
            if state == "done":
                text = f"✓ {r['seconds']:.1f} s" + (f" · {r['note']}" if r.get("note") else "")
            else:
                text = {"not run": "○ not run", "out of date": "⚠ run again"}[state]
    # Colour bar and text in one element, so they always change together; one line, cut with "…",
    # so every node keeps the same height.
    color = STATE_COLOR[state]
    STRIP[stage].markdown(
        f"<div style='padding:0 2px'><div style='height:4px;border-radius:2px;background:{color};margin:0 0 6px 0'></div>"
        f"<div title='{text}' style='color:{color};font-size:0.82rem;line-height:1.3;text-align:center;"
        f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{text}</div></div>", unsafe_allow_html=True)


def running(stage: str, text: str) -> None:
    node_status(stage, f"⏳ {text}", "running")


def strip():
    widths = []
    for i in range(len(ORDER)):
        widths += [3, 0.35] if i < len(ORDER) - 1 else [3]
    cols = st.container(key="strip").columns(widths, vertical_alignment="center")
    sel = C.selected()
    for i, stage in enumerate(ORDER):
        title, tip = C.STAGES[stage]
        with cols[2 * i].container(border=True, key=f"nodebox_{stage}"):
            st.button(title, key=f"node_{stage}", on_click=C.select, args=(stage,), help=tip,
                      use_container_width=True, type="primary" if stage == sel else "secondary")
            STRIP[stage] = st.empty()
            node_status(stage)
        if i < len(ORDER) - 1:
            cols[2 * i + 1].markdown("<div class='arrow'>→</div>", unsafe_allow_html=True)
    return st.empty()


def header(stage: str) -> bool:
    title, tip = C.STAGES[stage]
    a, b, c = st.columns([7, 0.8, 1.6], vertical_alignment="center")
    a.subheader(title, help=tip, anchor=False)
    with b.popover("ⓘ", use_container_width=True):
        st.markdown(ABOUT[stage])
    if stage == "result":
        return False
    state = C.status(stage)
    return c.button("▶ Run" if state == "not run" else "↻ Run again", key=f"run_{stage}", use_container_width=True,
                    type="primary" if state != "done" else "secondary")


def render(stage: str, run: bool = False, play: bool = False) -> bool:
    clicked = header(stage)
    VIEWS[stage](run or clicked, play) if stage == "forecast" else VIEWS[stage](run or clicked)
    node_status(stage)
    return clicked


def hint(text: str) -> None:
    st.caption(f"▶ {text}")


# ---------------------------------------------------------------- 1 sources

SOURCE_HELP = {
    "etryvoga": "Alerts that had started by 'now'. Oblast level, volunteer eTryvoga record; this is what is forecast.",
    "kpszsu": "Posts published by 'now' (since 1 Jan 2026): official threat tracks by region.",
    "povitryanatrivogaaa": "Posts published by 'now' (since 1 Jan 2026): volunteer drone routes, missiles, explosions.",
}


@st.cache_data(show_spinner=False)
def daily(name: str) -> pd.Series:
    src = C.source(name)
    f = src.frame
    col = "start_utc" if src.role == "alerts" else "published_at_utc"
    if src.role == "signals":
        f = f.drop_duplicates(["ref", "published_at_utc"])
    s = f.groupby(f[col].dt.floor("D")).size()
    return s[s.index >= pd.Timestamp("2026-01-01", tz="UTC")]


def source_card(name: str) -> None:
    t, src = C.now(), C.source(name)
    col = "start_utc" if src.role == "alerts" else "published_at_utc"
    before = src.frame[src.frame[col] < t]
    n = len(before) if src.role == "alerts" else len(before.drop_duplicates(["ref", "published_at_utc"]))
    unit = "alerts" if src.role == "alerts" else "posts"
    st.metric(f"{C.SOURCE_NAMES[name]} · {unit}", f"{n:,}", f"latest {C.kyiv(before[col].max(), '%d %b %H:%M')}",
              delta_color="off", help=SOURCE_HELP[name])
    d = daily(name)
    d = d[d.index < t]
    fig = go.Figure(go.Bar(x=C.local(d.index), y=d.values, marker_color=C.ALERT_RED if src.role == "alerts" else C.BLUE,
                           hovertemplate="%{x|%d %b}: %{y}<extra></extra>"))
    if t < C.LAST:
        fig.add_vrect(x0=C.local(t), x1=C.local(C.LAST) + pd.Timedelta(hours=12), fillcolor=C.GREY, opacity=0.12,
                      line_width=0)
    fig.update_xaxes(range=[pd.Timestamp("2026-01-01"), C.local(C.LAST) + pd.Timedelta(days=1)])
    C.show(C.small(fig, 150))


@st.cache_data(show_spinner=False)
def raw_alert_rows() -> pd.DataFrame:
    return pd.read_csv(github_csv.fetch(ALERT_FILE), parse_dates=["started_at", "finished_at"])


def live_posts_block(parsed: bool) -> None:
    live = st.session_state.get("live")
    a, b = st.columns([1.4, 5], vertical_alignment="center")
    if a.button("📡 Newest posts", key=f"live_{parsed}", use_container_width=True,
                help="Read the newest page of each channel straight from Telegram (about 20 posts each)."):
        try:
            with st.spinner("Asking t.me…"):
                S.fetch_live()
            live = st.session_state["live"]
        except Exception as exc:  # network trouble must not break the page
            st.error(f"Could not reach Telegram: {exc}")
    if not live:
        b.caption("Live: read both channels right now.")
        return
    newest = max(p["published_at_utc"].max() for p in live["posts"].values())
    b.caption(f"Live, fetched {C.kyiv(live['at'], '%H:%M:%S')}: newest post {C.kyiv(newest, '%H:%M')}. "
              "After the alert data ends, so not usable for a forecast yet.")
    rows = pd.concat([p.assign(channel=C.CHANNELS[ch]) for ch, p in live["posts"].items()])
    rows = rows.sort_values("published_at_utc", ascending=False)
    table = {"time": rows["published_at_utc"].dt.tz_convert(C.KYIV).dt.strftime("%H:%M"), "channel": rows["channel"]}
    if parsed:
        table |= {"kind": rows["kind"].replace({"drop": "—"}),
                  "regions": rows["regions"].map(lambda r: ", ".join(BY_CODE[c].name for c in r))}
    st.dataframe(pd.DataFrame(table | {"text": rows["text"]}), hide_index=True, height=220)


def v_sources(run: bool) -> None:
    done = C.status("sources") != "not run"
    cols = st.columns(3)
    t0 = time.time()
    for col, name in zip(cols, ["etryvoga", *P.SIGNALS]):
        with col:
            if run:
                running("sources", f"loading {C.SOURCE_NAMES[name].lower()}")
                with st.spinner(f"Loading {C.SOURCE_NAMES[name].lower()}…"):
                    C.source(name)
            if run or done:
                source_card(name)
            else:
                st.metric(f"{C.SOURCE_NAMES[name]}", "–", help=SOURCE_HELP[name])
    if run:
        C.record("sources", time.time() - t0)
    elif not done:
        hint("Run loads the three sources.")
        return
    live_posts_block(parsed=False)
    with st.popover("🔍 Raw data, before any processing"):
        t = C.now()
        raw = raw_alert_rows()
        st.dataframe(raw[raw["started_at"] < t].tail(6), hide_index=True)
        posts = C.classified("povitryanatrivogaaa")
        if posts is not None:
            p = posts[posts["published_at_utc"] < t].tail(6)
            st.dataframe(pd.DataFrame({"published": p["published_at_utc"].dt.tz_convert(C.KYIV).dt.strftime("%d %b %H:%M"),
                                       "text": p["text"]}), hide_index=True)


# ---------------------------------------------------------------- 2 parsing

EXAMPLES = {
    ("povitryanatrivogaaa", "Drone routes"): "✈️Київщина: →Богуслав/Тараща з Черкащини. ✈️Чернігівщина: →Ріпки/Славутич/Київщина (2х). ✈️Одещина: →Білгород-Дністровський/р-н з моря.",
    ("povitryanatrivogaaa", "Explosions"): "💥Макарів/околиці (Київщина) - вибухи",
    ("povitryanatrivogaaa", "Town not known"): "КАБ🚀→Б-Дністровський/р-н\nКАБ🚀→Маяки",
    ("kpszsu", "Missile"): "🚀 Ракета на Дніпропетровщині, повз Кривий Ріг курс північно-західний",
    ("kpszsu", "All clear"): "📢 Відбій загрози застосування балістичного озброєння.",
}


def kinds_chart(counts: dict[str, pd.Series], height=230):
    fig = go.Figure()
    for i, (label, s) in enumerate(counts.items()):
        fig.add_trace(go.Bar(y=s.index, x=s.values, orientation="h", name=label,
                             marker_color=[C.BLUE, C.AQUA][i % 2], hovertemplate="%{y}: %{x:,}<extra>" + label + "</extra>"))
    fig.update_layout(barmode="group", legend=dict(orientation="h", y=-0.2), yaxis=dict(autorange="reversed"))
    return C.small(fig, height)


def group_counts(kinds: pd.Series) -> pd.Series:
    g = kinds.map(lambda k: KIND_GROUPS.get(k, "dropped"))
    return g.value_counts().reindex(["drone", "missile", "aviation", "explosion", "clear", "dropped"], fill_value=0)


def parse_live() -> None:
    t0 = time.time()
    box = st.empty()
    with box.container(border=True):
        for ch in P.SIGNALS:
            src = registry()[ch]
            if not src.has_pages():
                C.set_classified(ch, None)
                continue
            running("parsing", f"reading {C.CHANNELS[ch]}")
            with st.spinner(f"Reading the downloaded pages of the {C.CHANNELS[ch]}…"):
                posts = load_posts(ch)
            bar, chart = st.progress(0.0), st.empty()
            kinds, regions, n, step = [], [], len(posts), 4000
            for i in range(0, n, step):
                texts = posts["text"].iloc[i:i + step]
                kinds += [classify(x, ch) for x in texts]
                regions += [find_regions(x) for x in texts]
                bar.progress(len(kinds) / n, f"{C.CHANNELS[ch]}: {len(kinds):,} of {n:,} posts parsed")
                running("parsing", f"{C.CHANNELS[ch]} {len(kinds) / n:.0%}")
                with chart.container():
                    C.show(kinds_chart({C.CHANNELS[ch]: group_counts(pd.Series(kinds))}, 200))
            posts["kind"], posts["regions"] = kinds, regions
            C.set_classified(ch, resolve_follow_ups(posts))
    box.empty()
    C.record("parsing", time.time() - t0)


def playground() -> None:
    pick = st.pills("Example", [f"{C.CHANNELS[ch]}: {name}" for ch, name in EXAMPLES], default=None,
                    label_visibility="collapsed")
    # Kept in plain session keys: Streamlit drops a widget's own state while its view is not shown.
    ss = st.session_state
    if pick and pick != ss.get("pg_pick"):  # load an example once, then let the user edit it
        ch, name = next(k for k in EXAMPLES if f"{C.CHANNELS[k[0]]}: {k[1]}" == pick)
        ss["pg_value"], ss["pg_ch_value"] = EXAMPLES[(ch, name)], ch
    ss["pg_pick"] = pick
    a, b = st.columns([3, 2])
    text = a.text_area("Try a post", value=ss.setdefault("pg_value", next(iter(EXAMPLES.values()))), height=110,
                       help="Real posts from October 2026, or type your own; the same rules run on every post.")
    channels = list(C.CHANNELS)
    channel = b.selectbox("Channel rules", channels, index=channels.index(ss.setdefault("pg_ch_value", channels[0])),
                          format_func=C.CHANNELS.get)
    ss["pg_value"], ss["pg_ch_value"] = text, channel
    clean = normalize(text)
    kind, regions = classify(clean, channel), find_regions(clean)
    b.markdown(f"**{kind if kind not in ('drop', 'follow_up') else 'no threat'}** · "
               f"{', '.join(BY_CODE[r].name for r in regions) or 'no region'}", help=explain(clean, channel))


def v_parsing(run: bool) -> None:
    if run:
        parse_live()
    playground()
    if C.status("parsing") == "not run":
        hint("Run parses every downloaded post, in batches.")
        return
    parsed = {ch: C.classified(ch) for ch in P.SIGNALS if C.classified(ch) is not None}
    t = C.now()
    if parsed:
        a, b = st.columns([2, 3])
        with a:
            C.show(kinds_chart({C.CHANNELS[ch]: group_counts(p["kind"]) for ch, p in parsed.items()}, 260))
            stats = {C.CHANNELS[ch]: (p.loc[~p["kind"].isin(["drop", "follow_up", "clear"]), "regions"].str.len() > 0).mean()
                     for ch, p in parsed.items()}
            st.caption(" · ".join(f"{k}: {v:.0%} of threat posts name a region" for k, v in stats.items()))
        with b:
            ch = st.segmented_control("Channel", list(parsed), default=list(parsed)[-1], format_func=C.CHANNELS.get,
                                      key="parse_channel", label_visibility="collapsed") or list(parsed)[-1]
            p = parsed[ch]
            p = p[p["published_at_utc"] < t].tail(12).iloc[::-1]
            st.dataframe(pd.DataFrame({
                "time": p["published_at_utc"].dt.tz_convert(C.KYIV).dt.strftime("%d %b %H:%M"),
                "kind": p["kind"].replace({"drop": "—"}),
                "regions": p["regions"].map(lambda r: ", ".join(BY_CODE[c].name for c in r)),
                "text": p["text"]}), hide_index=True, height=300)
    else:
        st.caption("Post texts are not in the repository (python -m airraid fetch downloads them); "
                   "parse the newest posts live instead:")
    live_posts_block(parsed=True)


# ---------------------------------------------------------------- 3 common format

def timeline(region: str, start: pd.Timestamp, end: pd.Timestamp):
    """Alerts and Telegram events for one region on one time axis, cut at the replay moment."""
    inp = P.known_at(C.inputs(), end)
    fig = go.Figure()
    a = inp.alerts.frame
    a = a[(a["region"] == region) & (a["end_utc"] > start)]
    for _, r in a.iterrows():
        x1 = min(r["end_utc"], end)
        fig.add_trace(go.Scatter(x=[C.local(r["start_utc"]), C.local(x1)], y=["alerts"] * 2, mode="lines",
                                 line=dict(color=C.ALERT_RED, width=14), showlegend=False,
                                 hovertemplate=f"alert {C.kyiv(r['start_utc'], '%H:%M')}–"
                                               f"{'running' if r['end_utc'] > end else C.kyiv(r['end_utc'], '%H:%M')}<extra></extra>"))
    seen = set()
    for src in inp.signals:
        f = src.frame
        f = f[(f["region"] == region) & (f["published_at_utc"] >= start)]
        if C.settings().exclude_edited:
            f = f[~f["edited"]]
        for group, g in f.groupby(f["kind"].map(KIND_GROUPS)):
            fig.add_trace(go.Scatter(x=C.local(g["published_at_utc"]), y=[C.CHANNELS[src.name]] * len(g), mode="markers",
                                     marker=dict(size=10, color=C.KIND_COLORS[group]), name=group, legendgroup=group,
                                     showlegend=group not in seen, hovertemplate=f"%{{x|%H:%M}} {group}<extra></extra>"))
            seen.add(group)
    C.now_line(fig, end)
    fig.update_layout(legend=dict(orientation="h", y=-0.3),
                      xaxis=dict(range=[C.local(start), C.local(end) + pd.Timedelta(hours=1)]),
                      yaxis=dict(categoryorder="array",
                                 categoryarray=[C.CHANNELS["kpszsu"], C.CHANNELS["povitryanatrivogaaa"], "alerts"]))
    return C.small(fig, 230)


def v_format(run: bool) -> None:
    t, s = C.now(), C.settings()
    if run:
        t0 = time.time()
        running("format", "building the hourly table")
        with st.spinner("Normalising and building the hourly table…"):
            S.hourly(t, s.max_alert_hours)
        C.record("format", time.time() - t0)
    if C.status("format") == "not run":
        hint("Run brings every source into one format and builds the hourly table.")
        return
    inp = C.inputs()
    st.markdown(" ".join(f":green-badge[✓ {C.SOURCE_NAMES[x.name]} · {len(x.frame):,} rows]" for x in [inp.alerts, *inp.signals]),
                help="Each source passed schema.validate: columns, UTC times, known regions and kinds, coverage period.")
    names = [BY_CODE[c].name for c in CODES]
    a, b = st.columns([3, 2], vertical_alignment="bottom")
    region = a.selectbox("Region", names, index=CODES.index("UA-63"), key="fmt_region", label_visibility="collapsed")
    hours = b.segmented_control("Window", [12, 24, 48], default=24, format_func=lambda h: f"last {h} h",
                                key="fmt_hours", label_visibility="collapsed") or 24
    C.show(timeline(CODES[names.index(region)], t - pd.Timedelta(hours=hours), t))
    H = S.hourly(t, s.max_alert_hours)
    last = H[H.index >= t - pd.Timedelta(hours=48)]
    order = last.mean().sort_values().index
    fig = go.Figure(go.Heatmap(z=last[order].T.values, x=C.local(last.index), y=[BY_CODE[c].name for c in order],
                               zmin=0, zmax=1, colorscale=[[0, C.theme()["ramp"][0]], [1, C.ALERT_RED]], showscale=False,
                               xgap=1, ygap=1, hovertemplate="%{y}, %{x|%d %b %H:00}: %{z:.0f}<extra></extra>"))
    C.show(C.small(fig, 440, "What the model receives: alert or not, per region and hour (last 48 h)"))


# ---------------------------------------------------------------- 4 patterns

def v_patterns(run: bool) -> None:
    t, s = C.now(), C.settings()
    if run:
        t0 = time.time()
        running("patterns", "computing")
        with st.spinner("Analysing the alert history…"):
            S.patterns(t, s.max_alert_hours)
        C.record("patterns", time.time() - t0)
    if C.status("patterns") == "not run":
        hint("Run analyses the alert history known at 'now'.")
        return
    R = S.patterns(t, s.max_alert_hours)
    a, b = st.columns(2)
    with a:
        m = R["monthly"]
        fig = go.Figure(go.Scatter(x=C.local(m.index), y=m.values, mode="lines", line=dict(color=C.BLUE, width=2),
                                   hovertemplate="%{x|%b %Y}: %{y:.0%}<extra></extra>"))
        fig.update_layout(yaxis=dict(tickformat=".0%", rangemode="tozero"))
        C.show(C.small(fig, 250, f"Alerts drift over months ({C.pct(m.min(), 0)}–{C.pct(m.max(), 0)} of region-hours) "
                                 "→ train on a rolling half-year"))
    with b:
        pe = R["persistence"]
        fig = go.Figure()
        for col, color, label in (("after_alert", C.ALERT_RED, "after an alert hour"),
                                  ("after_quiet", C.BLUE, "after a quiet hour")):
            fig.add_trace(go.Scatter(x=pe["h"], y=pe[col], mode="lines+markers", name=label, marker=dict(size=5),
                                     line=dict(color=color, width=2),
                                     hovertemplate=label + ", %{x} h later: %{y:+.0%}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"))
        fig.update_layout(legend=dict(orientation="h", y=-0.3), xaxis=dict(title="hours later", dtick=4),
                          yaxis=dict(tickformat="+.0%"))
        pa = pe.set_index("h")["after_alert"]
        C.show(C.small(fig, 250, f"An alert now: {pa[1] * 100:+.0f} pts next hour, {pa[12] * 100:+.0f} after 12 h "
                                 "→ the next hour is easy, later is hard"))
    a, b = st.columns(2)
    with a:
        prof = R["rhythm"]
        prof.index = [BY_CODE[c].name for c in prof.index]
        prof = prof.loc[prof.mean(axis=1).sort_values().index]
        fig = go.Figure(go.Heatmap(z=prof.values, x=prof.columns, y=prof.index, zmin=0, zmax=1, xgap=1, ygap=1,
                                   colorscale=C.ramp(), colorbar=dict(tickformat=".0%", thickness=8),
                                   hovertemplate="%{y}, %{x}:00 → %{z:.0%}<extra></extra>"))
        fig.update_layout(xaxis=dict(title="hour of day (Kyiv)", dtick=3))
        C.show(C.small(fig, 420, "Region matters far more than hour → the usual daily rhythm is the baseline"))
    with b:
        tg = R["together"]
        fig = go.Figure(go.Bar(x=tg.index, y=tg.values, marker_color=C.BLUE,
                               hovertemplate="%{x} regions at once: %{y:.0%} of hours<extra></extra>"))
        fig.update_layout(xaxis=dict(title="regions under alert in the same hour"), yaxis=dict(tickformat=".0%"))
        C.show(C.small(fig, 200, f"Regions go under alert together (neighbours r = {R['nb_corr']:.2f}, others "
                                 f"{R['other_corr']:.2f}) → neighbours are a feature"))
        d = R["durations"]
        fig = go.Figure(go.Histogram(x=d.clip(upper=24), xbins=dict(start=0, end=24.5, size=0.5), marker_color=C.BLUE,
                                     hovertemplate="%{x} h: %{y} alerts<extra></extra>"))
        fig.add_vline(x=s.max_alert_hours, line=dict(color=C.GREY, dash="dot"))
        fig.update_layout(xaxis=dict(title="hours (24 = 24 or more)"))
        C.show(C.small(fig, 200, f"Median alert {d.median() * 60:.0f} min; {C.pct((d > 12).mean())} over 12 h → capped"))


# ---------------------------------------------------------------- 5 model

def walk_chart(s: P.Settings, t: pd.Timestamp, blocks, states: dict, labels: dict):
    cfg = s.config()
    fig = go.Figure()
    color = {"pending": C.theme()["excluded"], "training": C.AMBER, "done": C.BLUE}
    for w, end in blocks:
        y = f"week of {C.kyiv(w, '%d %b')}"
        train_end = w - pd.Timedelta(hours=max(cfg.horizons))
        train_start = train_end - pd.Timedelta(days=cfg.train_days)
        fig.add_trace(go.Scatter(x=[C.local(train_start), C.local(train_end)], y=[y, y], mode="lines",
                                 line=dict(color=C.GREY, width=10), opacity=0.45, showlegend=False,
                                 hovertemplate=f"trained on {C.kyiv(train_start, '%d %b')} – {C.kyiv(train_end, '%d %b')}<extra></extra>"))
        fig.add_trace(go.Scatter(x=[C.local(w), C.local(end)], y=[y, y], mode="lines", showlegend=False,
                                 line=dict(color=color[states.get(w, "pending")], width=10),
                                 hovertemplate=f"forecasts made {C.kyiv(w, '%d %b')} – {C.kyiv(end, '%d %b %H:%M')}<extra></extra>"))
        if w in labels:
            fig.add_annotation(x=C.local(end), y=y, text=f"  {labels[w]}", showarrow=False, xanchor="left",
                               font=dict(size=12, color=C.BLUE if states.get(w) == "done" else C.AMBER))
    C.now_line(fig, t)
    fig.update_layout(yaxis=dict(autorange="reversed"), margin=dict(l=10, r=120, t=20, b=10))
    fig.update_layout(height=50 + 42 * len(blocks))
    return fig


def week_skill(pred: pd.DataFrame) -> str:
    g = pred[pred["h"] == 1]
    return f"next hour {C.skill(g['y'], g['p_main'], g['p_climatology']) * 100:+.0f}%"


def v_model(run: bool) -> None:
    s, t = C.settings(), C.now()
    blocks = P.scoring_weeks(s.config(), t, st.session_state.get("n_weeks", 4))
    if not blocks:
        hint("Move the clock later: no week can be scored yet.")
        return
    log, chart = st.empty(), st.empty()
    states, labels = {}, {}
    if run:
        t0 = time.time()
        with st.spinner("Building features from the data known at 'now'…"):
            running("model", "features")
            fs = C.features_now(s)
        out, reused = [], sum(C.has_models(s, w) for w, _ in blocks)
        for i, (w, end) in enumerate(blocks):
            states[w], labels[w] = "training", "training…"
            with chart.container():
                C.show(walk_chart(s, t, blocks, states, labels))
            short, long = C.models(fs, s, w, log=lambda m: (log.caption(m), running("model", f"week {i + 1}/{len(blocks)}")))
            pred = P.predict(fs, s, short, long, w, end).dropna(subset=["y"])
            out.append(pred)
            states[w], labels[w] = "done", week_skill(pred)
        log.empty()
        C.record("model", time.time() - t0, out=pd.concat(out, ignore_index=True),
                 note="models reused" if reused == len(blocks) else "")
        C.runs()["model"].update(blocks=blocks, t=t, s=s)  # what this run covered, to draw it as it was
    r = C.runs().get("model")
    if r is None:
        with chart.container():
            C.show(walk_chart(s, t, blocks, {}, {}))
        hint(f"Run trains {2 if s.channels else 1} model(s) per week on the data before it and scores its forecasts.")
        return
    pred = r["out"]
    blocks, t, s = r.get("blocks", blocks), r.get("t", t), r.get("s", s)  # the run as made, even if out of date
    starts = [w for w, _ in blocks]
    pos = pd.DatetimeIndex(starts).searchsorted(pred["t"], side="right") - 1
    labels = {starts[i]: week_skill(g) for i, g in pred.groupby(pos)}
    with chart.container():
        C.show(walk_chart(s, t, blocks, {w: "done" for w in labels}, labels))
    if C.status("model") == "out of date":
        st.caption("⚠ The clock or the inputs changed since this run.")
    elif r.get("note"):
        st.markdown(":gray-badge[♻ models reused]", help="A week's model depends only on the data before that week, "
                    "never on the clock, so models trained in an earlier run (by anyone using this app) are kept and "
                    "reused; this run only built the features and scored the forecasts.")
    q = pred[pred["active_now"] == 0]
    h1, q1, longer = pred[pred["h"] == 1], q[q["h"] == 1], pred[pred["h"] >= 4]
    m = st.columns(4)
    m[0].metric("Next hour", C.pct(C.skill(h1["y"], h1["p_main"], h1["p_climatology"])),
                help="% better than the usual daily rhythm, all forecast moments")
    m[1].metric("Next hour, no alert running", C.pct(C.skill(q1["y"], q1["p_main"], q1["p_climatology"])),
                help="Only moments with no alert running: will a new one start?")
    m[2].metric("4–24 h ahead", C.pct(C.skill(longer["y"], longer["p_main"], longer["p_climatology"])))
    gain = C.skill(q1["y"], q1["p_short"], q1["p_climatology"]) - C.skill(q1["y"], q1["p_long"], q1["p_climatology"])
    m[3].metric("Telegram gain, next hour", f"{gain * 100:+.1f} pts" if s.channels else "–",
                help="Telegram model minus alert-history model, moments with no alert running")
    rows = []
    for subset, g in (("all moments", pred), ("no alert running", q)):
        for h, gh in g[g["h"] >= 2].groupby("h"):
            rows.append({"subset": subset, "h": h, "skill": C.skill(gh["y"], gh["p_main"], gh["p_climatology"])})
    tab = pd.DataFrame(rows)
    same = pred.merge(C.ref()["pred"][["t", "region", "h", "p_main"]], on=["t", "region", "h"], suffixes=("", "_ref"))
    fig = go.Figure()
    for subset, color in (("all moments", C.BLUE), ("no alert running", C.AQUA)):
        g = tab[tab["subset"] == subset]
        fig.add_trace(go.Scatter(x=g["h"], y=g["skill"], mode="lines+markers", name=subset, marker=dict(size=5),
                                 line=dict(color=color, width=2.5), hovertemplate=subset + ", %{x} h: %{y:.1%}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"))
    fig.update_layout(legend=dict(orientation="h", y=-0.3), xaxis=dict(title="hours ahead", dtick=2),
                      yaxis=dict(tickformat=".0%"))
    C.show(C.small(fig, 280, "2–24 h ahead: % better than usual rhythm"))
    if len(same):
        diff = float((same["p_main"] - same["p_main_ref"]).abs().max())
        ok = diff < 1e-6
        st.markdown(f":{'green' if ok else 'gray'}-badge[{'✓ matches' if ok else '≠ differs from'} the committed run]",
                    help=f"{len(same):,} of these forecasts are also in results/predictions.parquet; largest difference "
                         f"in a probability {diff:.1e}" + ("" if ok or s == P.Settings() else
                                                           " (expected: the settings differ from the committed run)."))


# ---------------------------------------------------------------- 6 forecast

PRESET_RULES = {
    "Biggest attack": "the moment followed by the most region-hours under alert",
    "Quietest day": "the moment followed by the fewest region-hours under alert",
    "A good forecast": "where the model beat the usual daily rhythm by the widest margin over the next 24 hours",
    "A missed forecast": "where the model did worst against the usual daily rhythm over the next 24 hours",
}


@st.cache_data(show_spinner=False)
def presets() -> dict:
    """Example moments from the committed test weeks (a hit is always shown with a miss)."""
    test = C.ref()["test"]
    g = test.assign(e_main=(test["p_main"] - test["y"]) ** 2, e_clim=(test["p_climatology"] - test["y"]) ** 2)
    per_t = g.groupby("t").agg(alerts=("y", "sum"), e_main=("e_main", "sum"), e_clim=("e_clim", "sum"))
    per_t = per_t[g.groupby("t").size() == 24 * 24]
    gain = per_t["e_clim"] - per_t["e_main"]
    return {"Biggest attack": per_t["alerts"].idxmax(), "Quietest day": per_t["alerts"].idxmin(),
            "A good forecast": gain.idxmax(), "A missed forecast": gain.idxmin()}


def _jump():
    pick = st.session_state.get("jump")
    if pick:
        C.set_now(presets()[pick])
    st.session_state["jump"] = None


def compute_forecast(say) -> None:
    s, t = C.settings(), C.now()
    t0 = time.time()
    fs = C.features_now(s)
    week = P.week_of(s.config(), t)
    cached = C.has_models(s, week)
    short, long = C.models(fs, s, week, log=lambda m: (say(m), running("forecast", "training")))
    fc = P.predict(fs, s, short, long, t, t + P.HOUR)
    so_far = (P.predict(fs, s, short, long, week, t - pd.Timedelta(hours=23)).dropna(subset=["y"])
              if t - pd.Timedelta(hours=23) > week else pd.DataFrame())
    C.record("forecast", time.time() - t0, out={"fc": fc, "so_far": so_far, "week": week},
             note="model reused" if cached else "")


def draw_forecast(map_slot, side_slot, h: int, rhythm: bool, hindsight: bool, region: int) -> None:
    out, t, s = C.runs()["forecast"]["out"], C.now(), C.settings()
    fc, so_far = out["fc"], out["so_far"]
    rows = fc[fc["h"] == h].sort_values("region")
    codes = [CODES[i] for i in rows["region"]]
    probs = rows["p_climatology" if rhythm else "p_main"].to_numpy()
    target = t + pd.Timedelta(hours=h - 1)
    H = S.hourly(C.LAST, s.max_alert_hours)  # full history, used only for hindsight
    actual = H.loc[target, codes].to_numpy() if hindsight and target < C.LAST else None
    with map_slot.container():
        st.markdown(f"**{C.kyiv(t)}** → {C.hour_span(target)} · expected **{probs.sum():.1f}** regions under alert"
                    + (f" · actual **{int(np.nansum(actual))}**" if actual is not None else ""))
        C.show(C.ukraine_map(codes, probs, actual, "usual daily rhythm" if rhythm else "chance of an alert", 420))
    with side_slot.container():
        st.markdown(f"**This week's forecasts so far** (model of {C.kyiv(out['week'], '%d %b')})",
                    help="Forecasts made since the last retraining whose 24 hours have all passed by 'now'.")
        if len(so_far):
            g1 = so_far[so_far["h"] == 1]
            q1 = g1[g1["active_now"] == 0]
            m = st.columns(3)
            m[0].metric("checked", f"{so_far['t'].nunique()}", help="forecast moments with all 24 hours behind them")
            m[1].metric("next hour", C.pct(C.skill(g1["y"], g1["p_main"], g1["p_climatology"]), 0),
                        help="% better than the usual daily rhythm")
            m[2].metric("no alert running", C.pct(C.skill(q1["y"], q1["p_main"], q1["p_climatology"]), 0))
        else:
            st.caption("None yet: the week has just started.")
        one = fc[fc["region"] == region].sort_values("h")
        starts = one["t"] + pd.to_timedelta(one["h"] - 1, unit="h")
        act = np.array([H.at[x, CODES[region]] if x < C.LAST else np.nan for x in starts]) if hindsight else None
        st.markdown(f"**{BY_CODE[CODES[region]].name}, next 24 hours**")
        C.show(C.hourly_chart(starts, one["p_main"].to_numpy(), one["p_climatology"].to_numpy(), act, mark=target,
                              height=220))


def v_forecast(run: bool, play: bool = False) -> None:
    s, t = C.settings(), C.now()
    week = P.week_of(s.config(), t)
    names = [BY_CODE[c].name for c in CODES]
    c = st.columns([2.2, 1.6, 1.2, 1.4, 1.6], vertical_alignment="bottom")
    h = c[0].slider("Hours ahead", 1, 24, 1, help="1 = the hour right after the forecast is made.")
    rhythm = c[1].segmented_control("Colour by", ["Forecast", "Usual rhythm"], default="Forecast") == "Usual rhythm"
    hindsight = c[2].toggle("What happened", help="Hindsight: outcomes after 'now', never seen by the model.")
    region = names.index(c[3].selectbox("Region", names, index=CODES.index("UA-30"), key="fc_region"))
    c[4].selectbox("Jump to", list(PRESET_RULES), index=None, key="jump", on_change=_jump, placeholder="an example…",
                   help="; ".join(f"{k}: {v}" for k, v in PRESET_RULES.items()) + " (test weeks).")
    say = st.empty()
    left, right = st.columns([3, 2])
    map_slot, side_slot = left.empty(), right.empty()
    ready = C.has_models(s, week)
    if run or play or (ready and C.status("forecast") != "done"):
        if not ready:
            say.caption(f"New week: training the model for the week of {C.kyiv(week, '%d %b')} on the data before it…")
        compute_forecast(say.caption)
        say.empty()
    if C.status("forecast") == "not run":
        hint(f"Run trains the model for the week of {C.kyiv(week, '%d %b')} and forecasts the next 24 hours.")
        return
    draw_forecast(map_slot, side_slot, h, rhythm, hindsight, region)
    if play:
        for _ in range(24):
            if C.now() >= C.LAST:
                break
            C.set_now(C.now() + P.HOUR)
            running("forecast", C.kyiv(C.now(), "%d %b %H:%M"))
            compute_forecast(say.caption)
            say.empty()
            draw_forecast(map_slot, side_slot, h, rhythm, hindsight, region)
            time.sleep(0.3)


# ---------------------------------------------------------------- 7 result

def decision(test: pd.DataFrame) -> None:
    q = test[(test["h"] == 1) & (test["active_now"] == 0)]
    days = q["t"].dt.floor("D").nunique()
    thr = st.slider("Warn a region when the chance of a new alert next hour is at least", 0.05, 0.9, 0.3, 0.05,
                    key="warn_thr")
    n = int((q["p_main"] >= thr).sum())
    st.caption(f"{n / days:.0f} warnings a day for both rows", help="Test weeks, moments with no alert running. The "
               "usual daily rhythm gets the same number of warnings (its top picks), so the rows compare where each "
               "one puts them.")
    rows = []
    for col, label in (("p_main", "Forecast"), ("p_climatology", "Usual daily rhythm")):
        warn = q[col].rank(method="first", ascending=False) <= n  # same number of warnings for both
        hit = (warn & (q["y"] == 1)).sum()
        rows.append({"based on": label, "alerts caught": hit / max((q["y"] == 1).sum(), 1),
                     "false alarms / day": (warn & (q["y"] == 0)).sum() / days, "came true": hit / max(warn.sum(), 1)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={
        "alerts caught": st.column_config.NumberColumn(format="percent"),
        "came true": st.column_config.NumberColumn(format="percent"),
        "false alarms / day": st.column_config.NumberColumn(format="%.0f")})


def v_result(run: bool) -> None:
    ref = C.ref()
    test, unc = ref["test"], ref["unc"]
    nh, nh_lo, nh_hi = C.ci(unc, "main_vs_climatology", "test", "all", 1)
    nq, nq_lo, nq_hi = C.ci(unc, "main_vs_climatology", "test", "quiet", 1)
    lg, lg_lo, lg_hi = C.ci(unc, "main_vs_climatology", "test", "all", "4-24")
    tg, tg_lo, tg_hi = C.ci(unc, "alertmap_minus_none", "test", "quiet", 1)
    m = st.columns(4)
    m[0].metric("Next hour", f"{nh * 100:.0f}% better", help=f"than the usual daily rhythm; 95%: {C.pct(nh_lo)}–{C.pct(nh_hi)}. "
                "Mostly because a running alert continues.")
    m[1].metric("Next hour, no alert running", f"{nq * 100:.1f}% better", help=f"95%: {C.pct(nq_lo)}–{C.pct(nq_hi)}")
    m[2].metric("4–24 hours ahead", f"{lg * 100:.1f}% better", help=f"95%: {C.pct(lg_lo)}–{C.pct(lg_hi)}. Further ahead "
                "the usual daily rhythm is hard to beat.")
    m[3].metric("Telegram, next hour", f"+{tg * 100:.1f} pts", help=f"Alert-map channel, no alert running; 95%: "
                f"{tg_lo * 100:+.1f} to {tg_hi * 100:+.1f}. Nothing measurable from 4 hours on.")
    a, b = st.columns(2)
    with a:
        u = unc[(unc["metric"] == "main_vs_climatology") & (unc["period"] == "test")]
        fig = go.Figure()
        for subset, color, label in (("all", C.BLUE, "all moments"), ("quiet", C.AQUA, "no alert running")):
            g = u[(u["subset"] == subset) & u["h"].str.isdigit()].assign(h=lambda d: d["h"].astype(int)).query("h >= 2")
            g = g.sort_values("h")
            fig.add_trace(go.Scatter(x=pd.concat([g["h"], g["h"][::-1]]), y=pd.concat([g["hi"], g["lo"][::-1]]),
                                     fill="toself", fillcolor=color, opacity=0.15, line=dict(width=0), hoverinfo="skip",
                                     showlegend=False))
            fig.add_trace(go.Scatter(x=g["h"], y=g["point"], mode="lines", name=label, line=dict(color=color, width=2.5),
                                     hovertemplate=label + ", %{x} h: %{y:.1%}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"))
        fig.update_layout(legend=dict(orientation="h", y=-0.3), xaxis=dict(title="hours ahead", dtick=2),
                          yaxis=dict(tickformat=".0%"))
        C.show(C.small(fig, 300, "2–24 h ahead: % better than usual rhythm"))
    with b:
        fig = go.Figure()
        for period, color, dash in (("validation", C.GREY, "dash"), ("test", C.BLUE, "solid")):
            g = unc[(unc["metric"] == "alertmap_minus_none") & (unc["period"] == period) & (unc["subset"] == "quiet")]
            g = g[g["h"].str.isdigit()].assign(h=lambda d: d["h"].astype(int)).sort_values("h")
            fig.add_trace(go.Scatter(x=pd.concat([g["h"], g["h"][::-1]]), y=pd.concat([g["hi"], g["lo"][::-1]]),
                                     fill="toself", fillcolor=color, opacity=0.12, line=dict(width=0), hoverinfo="skip",
                                     showlegend=False))
            fig.add_trace(go.Scatter(x=g["h"], y=g["point"], mode="lines", name=f"{period} weeks",
                                     line=dict(color=color, width=2.5, dash=dash),
                                     hovertemplate=period + ", %{x} h: %{y:+.1%}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color=C.GREY, width=1, dash="dot"))
        fig.add_vline(x=SHORT_HORIZON + 0.5, line=dict(color=C.GREY, width=1))
        fig.update_layout(legend=dict(orientation="h", y=-0.3), xaxis=dict(title="hours ahead", dtick=2),
                          yaxis=dict(tickformat="+.1%"))
        C.show(C.small(fig, 300, "What Telegram adds → used up to 3 h"))
    a, b = st.columns([3, 2])
    with a:
        decision(test)
    with b:
        alerts = test[test["h"] == 1].groupby("region")["y"].mean()
        br = ref["by_region"]
        br = br[(br["model"] == "main") & br["region"].map(alerts).gt(0)].sort_values("brier_skill")
        fig = go.Figure(go.Bar(x=br["brier_skill"], y=br["region_name"], orientation="h",
                               marker_color=np.where(br["brier_skill"] > 0, C.BLUE, C.GREY),
                               hovertemplate="%{y}: %{x:.1%}<extra></extra>"))
        fig.update_layout(xaxis=dict(tickformat=".0%"), yaxis=dict(tickfont=dict(size=10)))
        C.show(C.small(fig, 420, "By region (grey = worse than rhythm)"))
    r = C.runs().get("model")
    if r is not None and len(r["out"]):
        st.caption("Stage 5 holds your own run of the model with the current inputs; this page is the committed run.")


VIEWS = {"sources": v_sources, "parsing": v_parsing, "format": v_format, "patterns": v_patterns,
         "model": v_model, "forecast": v_forecast, "result": v_result}
