# Review: structure and redesign (independent subagent, verbatim)

## 1. What is structurally wrong

- **The app is organised by kind of output, not by the visitor's questions.** The tabs Map / Accuracy / Sources / Data don't tell anyone what they will learn. "What is this, and is it any good" sits in one grey caption (G2). The findings exist only in the README: the app shows numbers but never states a conclusion.
- **The main interaction exposes the model's internals.** "Issued at" × "hours ahead" × "model" gives 673 × 24 × 6 combinations. It also puts two different things on one slider: the forecast itself (the latest run) and its evaluation (the replay).
- **The researcher's view leaks into the visitor's view.** The 7 models appear in different subsets on 3 tabs, and one tab's setting changes another tab (A2 → S3). A visitor only needs "forecast vs baseline"; the source-set comparisons are evidence for a claim and belong in the accuracy section.
- **The evidence charts don't show the claims.** Bare tiles like "0.065" have no unit or reference. Telegram is shown as 4 crossing lines. **A7 is effectively broken:** Zakarpattia has skill −681 (almost no alerts, so the baseline error is about 0). That stretches the axis and every other bar becomes invisible (`results/metrics_by_region.csv`, `light_accuracy_all_3.png`).
- **The project's strongest points for a reviewer are missing or buried:** where the data comes from, the official-vs-volunteer disagreement, the leakage safeguards and the limitations.

## 2. Proposed structure: one page, four sections, each a question

Replace the tabs with one scrolling page. Wrap the explorer in `@st.fragment` so its widgets rerun only that part (this fixes the greyed-out page).

0. **Hero (first screen): "What is this, and does it work?"** A rail on the left with the findings and sources, the map on the right.
1. **Explorer: "What's expected in the next 24 h, and what did it predict before?"** The map plus the 24-hour chart for one region.
2. **"How accurate is it?"** Three charts, each titled with its finding.
3. **"Where does the data come from?"** Source cards and the daily-rhythm heatmap.
4. **"How was it tested, and what are the limits?"** Text, partly in expanders.

**First screen (1440×900):**
```
 Air-raid alert forecast · Ukraine · next 24 hours, by region
 Chance of an alert in each region for each of the next 24 h. Learned from alert
 history + 2 Telegram channels; tested on 4 weeks it never saw (14 Sep–12 Oct).
┌─────────────────────────┬──────────────────────────────────────────────────┐
│ WHAT WE FOUND           │ (●Next 24 h)(Biggest attack)(Quiet night)(A miss)│
│ 1 Next hour: 26% lower  │ (A hit)(Pick a date…)   Colour by: [Forecast|Baseline]
│   error than baseline   │ ┌───────────────────────────────┐ Expected under │
│   (6.5% if no alert now)│ │                               │ alert: 7.8 of 24│
│ 2 Beyond ~3 h: 1–2% —   │ │      MAP (one target hour)    │ Actual: — (no   │
│   daily rhythm wins     │ │      click a region ↓         │ outcome yet)    │
│ 3 Telegram helps 1–3 h  │ └───────────────────────────────┘                 │
│ DATA  eTryvoga alerts · │ ▶ +1h ━●━━━━━━━━━━━━━━━━ +24h  04:00–05:00 Mon 12 Oct
│ @kpszsu · @povitryana…  │ ■ chance of alert  ▢ red = alert happened  ▒ grey = not forecast
│ ↓Accuracy ↓Data ↓Limits │                                                  │
└─────────────────────────┴──────────────────────────────────────────────────┘
```

**The explorer in replay mode (below the fold):**
```
 Replay · forecast made [Tue 30 Sep ▾] [03:00 ▾]  [◀ −1 h] [+1 h ▶]
 MAP with red outlines, ▶ plays +1…+24 h            Expected 9.4 · Actual 13
 ── Kyiv City: the 24 forecasts made at 03:00 ──────────────────────────────
 [line: forecast vs dashed baseline; red bars = hours with an alert; box = map hour]
 ▸ Track record in this region (±3 days, same lead time)       (M13)
 ▸ Colour by another model (replay only)
```

## 3. What happens to each current element

**Global**
- G1: keep, shortened.
- G2: split into the hero sentence and the DATA rail.
- G3: cut, replaced by the four question headers plus anchor links in the rail.
- G4: keep.
- G5: hide with `[client] toolbarMode="viewer"`.

**Map tab**
- M1: replace with the mode/preset pills, date and hour pickers, and ±1 h buttons.
- M2: move into the map as a Plotly animation slider with ▶. It runs in the browser, so there is no rerun.
- M3: merge into the frame label.
- M4: cut down to "Forecast | Baseline". The other source sets appear only in section 2.
- M5: keep. Make it clickable and fix the dark-mode colour ramp.
- M6: replace with "Expected regions under alert" (the sum of probabilities), which avoids the arbitrary 50% threshold.
- M7: keep, as "Actual" next to the expected count.
- M8: move into an expander (an error score for one hour is noise).
- M9: cut, no longer needed.
- M10: move to a one-line legend under the map.
- M11: replace with a click on the map; keep a small selectbox as fallback.
- M12: keep, directly under the map.
- M13: move into an expander.

**Accuracy tab**
- A1: merge. The chart title becomes the finding; the jargon goes into `help=` tooltips.
- A2: cut. Show "all moments" and "quiet moments" as two lines in one chart instead of a toggle.
- A3: cut. The h=1 values become labelled points; the headline number sits in the rail.
- A4: merge into "Skill by hours ahead": main model only, 2 lines plus a zero line for the baseline. Other models go in a "Compare all models" expander.
- A5: move into an expander with readable column names.
- A6: keep, in section 2.
- A7: fix (drop regions with under 2% alert hours, or clip the axis), then put it in an expander, ideally as a choropleth.

**Sources tab**
- S1: becomes section 2's finding 3.
- S2: cut.
- S3: replace with bars showing the gain over the no-Telegram model, per channel, by hour ahead, at quiet moments. This only subtracts columns of `metrics_by_horizon_quiet`.
- S4: split. The edited-posts note goes to section 4; "why this main model" becomes the S3 caption.
- S5: becomes 3 source cards (what it is, period, posts, % mapped to a region, % edited and excluded). The raw table goes in an expander.

**Data tab**
- D1: keep in section 3, retitled "The daily rhythm the baseline uses".
- D2: move into an expander, with the test period shaded.

**New, from data the app already has**
- Official-vs-volunteer agreement (`alert_source_agreement.csv`, 81%) in a section 3 expander.
- The leakage safeguards and limitations from the README as section 4 text.

## 4. Controls and defaults

| Control | Default |
|---|---|
| Mode/preset pills (`st.pills`) | **Next 24 h** |
| Date and hour (Kyiv time), plus −1 h / +1 h buttons | shown only in replay |
| Hours ahead: Plotly animation slider with ▶ | **+1 h** |
| Colour by | **Forecast** (other option: Baseline) |
| Region | **Kyiv City**; a click on the map changes it |

How the presets and controls work:
- **The presets are computed once (cached) from `predictions.parquet` (test period only):**
  - Biggest attack: the issue hour whose next 24 h had the most region-hours under alert.
  - Quiet night: the issue hour with the fewest.
  - A miss / a hit: the issue hour where the main model's error was furthest above / below the baseline.
  - Showing a miss next to a hit avoids looking cherry-picked.
- **Date and hour:** `st.date_input` limited to 14 Sep–11 Oct, plus an hour selectbox. The ±1 h buttons update `session_state`. Put the chosen moment in `st.query_params` so a link reopens the same view.
- **Region click:** `st.plotly_chart(on_select="rerun")`, which Streamlit 1.65 supports.
- Lay the control row out with `st.columns(vertical_alignment="bottom")` and short labels. This fixes the wrapping label that pushed the hours slider down.
- Section 2 has no controls; everything extra goes in expanders.

## 5. Effort (rough, for a competent Streamlit developer)

| Work | Hours |
|---|---|
| One page with question headers and the hero rail | 1.5 |
| Pills, presets and date/hour/±1 h controls | 1.5 |
| Animated map with frames (fill and outlines per frame) | 1.5–2 |
| Click a region to select it | 0.5 |
| Section 2 rebuild (two-line skill chart, Telegram gain bars, A7 fix, expanders) | 2 |
| Section 3 cards, agreement chart, heatmap retitle | 1.5 |
| Section 4 text, fragment, config, dark-mode ramp | 1 |
| **Total** | **about 9–10** |

**If only about 2 hours are available, do these in order:**
1. Fix A7. A visibly broken chart hurts credibility most. (15 min)
2. Hero rail with the 3 findings and sources, tabs replaced by question headers, toolbar hidden. (45 min)
3. Mode pills (Next 24 h, Biggest attack, A miss, A hit) plus the date/hour pickers instead of the 673-position slider. Cut M4 to Forecast/Baseline, replace M6 with expected vs actual, delete M9. (45 min)
4. Section 2: one skill chart with all/quiet lines (replaces A2–A4) and Telegram gain bars (replaces S2–S3); tables into expanders. (30 min)

The animated map and click-to-select can wait; the hours slider can stay as a plain slider inside the fragment for now.

The reviewer changed no files.
