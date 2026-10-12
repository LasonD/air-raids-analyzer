# UI inventory (state at commit b041c79)

Input for the independent UI review. Describes what the Streamlit app (`app.py`) shows today, where each
element's data comes from and the problems already known. Screenshots: `docs/ui-review/screens/`
(`light_*`, `dark_*` at 1440×900, `narrow_*` at 900×900; `_1/_2/_3` = scroll positions top to bottom).

## What the app is for

A pet project for a KSE admission task: forecast, per region of Ukraine, the probability of an air raid
alert in each of the next 24 hours, evaluated on the last 4 weeks of data with no look-ahead. The app is
how a reviewer (or anyone) sees that it works. It must make obvious **what this is, what it does, where
the data comes from, and what one can do with it**. Started with `python -m airraid gui`; reads only
precomputed files in `results/`.

## Data the app can draw on (no recomputation needed)

| File | Content |
|---|---|
| `results/predictions.parquet` | 767k rows: issue time `t` (UTC, hourly, 17 Aug – 11 Oct), `region` (0–23), horizon `h` (1–24), outcome `y`, `active_now` (alert running at t), `period` (validation/test), probability per model: `p_main`, `p_gbm_none`, `p_gbm_kpszsu`, `p_gbm_alertmap`, `p_gbm_both`, `p_logistic`, `p_climatology`, `p_persistence` |
| `results/forecast_latest.parquet` | latest forecast: issue 12 Oct 00:00 UTC, 24 regions × 24 horizons, `p` (main), `p_climatology` |
| `results/metrics_overall.csv`, `metrics_by_horizon*.csv`, `metrics_by_region.csv` | Brier, log loss, AUC, Brier skill per model (and per horizon / region); `_quiet` = no alert running at issue time; `*_with_edited.*` = comparison run keeping edited Telegram posts |
| `results/hourly_alerts.parquet` | 2026 hourly alert matrix, hour × region (0/1) |
| `results/source_health.json` | per source: coverage period, record counts, parse rates |
| `results/alert_source_agreement.csv` | official vs volunteer alert data agreement per region (Jun–Sep) |
| `airraid/assets/ukraine_adm1.geojson` | oblast boundaries (ODbL) |

Key results the UI should convey (from README): best skill is the next hour; beyond ~3 h the daily rhythm
(climatology) is hard to beat (all models only 1–2 % better); Telegram (alert-map channel) helps for 1–3 h
at quiet moments (next-hour skill 0.054 → 0.065); main model = alert-map features for 1–3 h, alert history
after (chosen on validation); edited Telegram posts excluded (possible leakage).

## Global elements

| # | Element | Notes |
|---|---|---|
| G1 | Title "Air raid alerts in Ukraine: 24-hour forecast" | |
| G2 | Caption: one paragraph with definition, test period, sources | dense, small grey text; the only place sources are named |
| G3 | Tabs: Map replay · Accuracy · Sources · Data | tab names don't say what each answers |
| G4 | Footer: boundaries attribution | |
| G5 | Streamlit chrome: "Deploy" button, ⋮ menu, run/stop indicator | not ours; can be hidden via config |

## Tab "Map replay" (`light_map_latest_*`, `light_map_replay_*`)

| # | Element | Shows / does | Data |
|---|---|---|---|
| M1 | Select-slider "Forecast issued at (Kyiv time); the right end is the latest forecast, with no outcome yet" | 673 positions: every hour of the test period + "▶ latest forecast"; default = latest | predictions `t` |
| M2 | Slider "Hours ahead (1 = the hour right after the forecast)" 1–24, default 6 | which single hour after issue is mapped | |
| M3 | Caption under M2 "→ the hour 13:00–14:00, Wed 30 Sep (Kyiv), forecast at …" | | |
| M4 | Radio "Model": Main model / Alert-map only / Both channels / Air Force only / No Telegram / Climatology baseline | colours the map by that model | |
| M5 | Choropleth map, title "Hour HH–HH, date · forecast issued …" | fill = probability (blue ramp 0–100 %), red outline = alert happened (replay only), grey = Luhansk/Crimea | predictions / forecast_latest |
| M6 | Side panel "At this moment": metric "Regions forecast ≥ 50 %" | count | |
| M7 | metric "Regions with an alert (red outline)" (replay only) | count | |
| M8 | metric "Brier score now" + delta vs climatology (replay only) | one hour, 24 regions | |
| M9 | Info box (latest only): "Latest forecast … computed for the main model and climatology only …" | | |
| M10 | Caption: legend for fill / red outline / grey | | |
| M11 | Selectbox "Region" (default Kyiv City) | drives M12/M13 | |
| M12 | Chart "<region>: the 24 hourly forecasts made at <issue>": model line, climatology dashed, alert hours shaded red, "map hour" box | | |
| M13 | Chart "<region>: forecasts made h h before each hour, ±3 days … vs what happened" (replay only) | | |

## Tab "Accuracy" (`light_accuracy_all_*`, `light_accuracy_quiet_*`)

| # | Element | Notes |
|---|---|---|
| A1 | Heading "Brier skill vs climatology by forecast horizon (test period; above 0 = better …)" | jargon: Brier skill, horizon, climatology |
| A2 | Radio "Moments scored": All issue times / Only when no alert is running at issue time (+ help tooltip) | also silently drives the Sources tab chart |
| A3 | 4 metric tiles "Next hour (h = 1)": Main / alert history only / both channels / logistic | raw skill numbers like 0.065, no unit or reference |
| A4 | Line chart, 2–24 h: Main, alert-history only, logistic, climatology (0 line) | main and alert-history lines coincide from 4 h (explained in text) |
| A5 | Table "Overall scores": period × model × brier, log_loss, auc, brier_skill, n (~24 rows) | raw column names |
| A6 | Calibration chart (main model) | |
| A7 | Horizontal bar chart: Brier skill by region (main) | |

## Tab "Sources" (`light_sources_*`)

| # | Element | Notes |
|---|---|---|
| S1 | Heading "Does Telegram help? …" | |
| S2 | 4 metric tiles, next hour, per source set | |
| S3 | Line chart 2–24 h: both / none / Air Force / alert-map | 4 close, crossing lines |
| S4 | Caption: follows "Moments scored" on the Accuracy tab; edited posts excluded; why main model | cross-tab dependency |
| S5 | Table "Source health": source, role, covered_from/to (raw timestamps), records, kept_posts, threat_posts_with_region, edited_posts, days_under_50_posts | "None" cells; raw names |

Not shown anywhere: what each Telegram channel is / example posts / how posts become features; the
official-vs-volunteer disagreement; the leakage safeguards.

## Tab "Data" (`light_data_*`)

| # | Element | Notes |
|---|---|---|
| D1 | Heatmap: share of hours under alert, region × hour of day (Kyiv), 2026 | sorted by mean |
| D2 | Line: share of region-hours under alert by week | |

## Problems already known (from my own checks)

1. **Misaligned controls**: the long M2 label wraps to two lines, pushing the hours slider below M1
   (user screenshot; also `narrow_map_latest_1`).
2. **Stale state while re-running**: after moving a slider the whole page greys out and briefly shows old
   values (each change re-runs the script; the map takes ~1 s).
3. M1 has 673 positions; reaching a specific hour with mouse or keyboard is fiddly.
4. **Dark mode**: on the dark background the *lowest* probabilities are the brightest regions (the blue
   ramp is light-to-dark for a light surface), so attention goes to the least likely regions.
5. In the latest-forecast view, M4 offers 6 models but only main/climatology exist (others silently show
   main, explained in M9).
6. M6 "≥ 50 %" is an arbitrary threshold; most probabilities sit between 20 and 60 %.
7. Jargon throughout: Brier skill, horizon, climatology, persistence, quiet moments, validation/test.
8. A2 ("Moments scored") on the Accuracy tab also changes the Sources tab chart.
9. Tables (A5, S5) show raw column names, "None", full timestamps.
10. Model choices (M4, A3, S2, S3) repeat the same seven models in different subsets on three tabs.
