# Review: visual design and charts (independent subagent, verbatim)

## 1. Verdict
The app has the right ingredients: one blue ramp, fixed model colours and a single map as the hero. But the title and three mismatched controls take up the first viewport, so the map starts halfway down the screen (y≈490 at 1440 px wide, y≈770 at 900 px). Several charts hide or distort their own point: one outlier flattens the region bar chart, the orange line is drawn over the main model's line, and dark mode makes the least likely regions and the excluded regions the brightest things on the map. Most fixes are config or Plotly parameters, not redesigns.

## 2. Findings
| ID | Sev | Where | Problem | Recommendation | Effort |
|---|---|---|---|---|---|
| V1 | blocker | A7 · light_accuracy_all_3 | Zakarpattia at −650 squeezes the other 23 bars into invisible slivers | Clip the x-axis to about ±0.15. Draw Zakarpattia as a clipped bar with the text "−650, off scale". Colour bars below 0 in NEUTRAL grey | S |
| V2 | major | M5, D1 · dark_map_latest_1, dark_data_1 | In dark mode the lowest probabilities are brightest, the #d9d8d4 grey on Luhansk/Crimea is the brightest patch, and the white borders glow | Choose the ramp with `st.context.theme.type` (Streamlit 1.65 has it). Dark ramp: near-surface navy (#1a2b45) up to #cde2fb. Region borders = page background colour. Excluded fill = a neutral close to the surface in each theme | M |
| V3 | major | G3, M1, M2, M4, M8 · all screens | Streamlit's default red is on the active tab, slider tracks and values, radio dots and the M8 delta pill. That clashes with "red = alert happened" | Set `primaryColor="#2a78d6"`, or a neutral ink colour, under `[theme.light]`/`[theme.dark]` so auto light/dark still works. Use `delta_color="off"` on M8 | S |
| V4 | major | A4 · light_accuracy_all_1 | The main model is drawn first, so from 4 h the orange line covers it and the main model disappears. Climatology appears twice (grey markers plus the dotted zero line) | Draw main last at 3 px, others at 1.5 px. Drop the climatology trace and label the zero line "climatology". Use direct end-of-line labels instead of the far-away legend | S |
| V5 | major | A3, S2 tiles | The largest text in each tab is a bare 0.258 or 0.111 with no unit. Tile order differs from legend order on Sources | Accuracy: one `make_subplots` 1×2 figure, left = next-hour dot plot per model with its own y-axis, right = 2–24 h lines. Format skill as "% better than climatology" (`tickformat=".0%"`). Sources: plot Δ skill against "alert history only" for h=1–24 on one axis. h=1 then fits on the same scale, so the tiles can go | M |
| V6 | major | M1–M4 · light_map_latest_1, narrow_map_latest_1 | The wrapped M2 label pushes its slider about 20 px below M1. The 6-row vertical radio makes the control row about 180 px tall, with dead space under M1 | Short labels ("Forecast made at", "Hours ahead") with the detail moved into `help=`. Turn M4 into `st.segmented_control` or a selectbox. Make the H1 smaller | S |
| V7 | major | M5 outline · light_map_replay_1 | 13 neighbouring outlines merge into a red mesh. Red vs mid-blue luminance contrast is about 1.3:1, so it's unclear which side of a shared border had the alert | Draw a halo (alerted outlines first in surface colour at 6 px, then red at 2.5 px), or use red ring markers at region centroids via Scattergeo | M |
| V8 | minor | M3, M5 title, M12 title | The same "hour … forecast issued …" text appears 3 times | Keep it once, as a Streamlit subheader above the map | S |
| V9 | minor | M5 colourbar · light_map_latest_2 | The vertical bar sits about 80 px from the map and is taller than the country, leaving about 100 px blank below | Horizontal colourbar under the map (`orientation="h"`, `thickness=10`, `len=.5`), map height about 420 | S |
| V10 | minor | M12, M13 · light/dark_map_replay_2 | Full-height alert columns are the strongest mark on the chart. The 0–100 % axis leaves about 55 % of it empty. 144 markers add noise. In dark mode the 0.25-opacity red turns muddy maroon | Show alerts as a red strip along the x-axis (y 0–0.04). Use y 0–60 % unless the data go higher. Use `mode="lines"`. Mark the map hour with a vline plus a ring on the point | S |
| V11 | minor | A5, S5 | Raw column names, 4 decimals, an n column that never changes, "None", +00:00 timestamps, and a scrollbar nested inside the page scroll | Use `column_config` labels and formats. Pivot A5 to one row per model (test period) and put validation in an expander. S5: show dates as "1 Jan – 12 Oct 2026" and "—" for empty cells | S |
| V12 | minor | All Plotly charts, G5 | The Plotly toolbar covers chart corners (A6, S3). The Deploy button shows | `config={"displayModeBar": False}` on every chart. `[client] toolbarMode="viewer"` | S |
| V13 | minor | M6–M10 · narrow_map_latest_1/2 | Bare counts and an arbitrary threshold. The info box is the biggest coloured block. At 900 px the side column becomes 8+ lines of narrow text | Remove the side column. Put one sentence above the map ("13 of 24 regions had an alert …") and a swatch legend below it | M |
| V14 | minor | S3 | The Air Force yellow #eda100 is about 2:1 on white. Pink and orange are close for colour-blind viewers | Darken to about #b57d00 or swap for teal, then check in a colour-blindness simulator | S |
| V15 | minor | D2 · light_data_2 | The end points are probably partial weeks and spike (check). Markers on 40 points add noise | Drop or mark partial weeks. Lines only | S |
| V16 | minor | G1, G2 | G2 lines run to about 180 characters. The H1 wraps to 2 lines at 900 px | Cap the caption at about 75 characters wide. Use a smaller H1 | S |

## 3. Per-element verdicts
- **M3**: cut. It repeats the map title.
- **M6**: cut. The ≥50 % threshold is arbitrary.
- **M7, M8**: merge into one sentence above the map, with no red pill.
- **M9**: shrink to a one-line caption, and disable the M4 options that have no latest forecast.
- **M10**: replace with a swatch legend (ramp, red outline, grey).
- **M11**: narrow to about 300 px and put it in the same row as the M12 title.
- **M13**: move into an expander, restyled as in V10.
- **A3**: replace with the split panel (V5).
- **A4**: restyle (V4).
- **A5**: pivot and format.
- **A6**: keep. Set equal axis scaling so the diagonal sits at 45°, and label "perfect" on the line instead of in a legend.
- **A7**: fix the axis (V1). An alternative is a diverging region map.
- **S2**: cut, because the Δ chart covers h=1.
- **S3**: replace with the Δ-vs-no-Telegram chart.
- **S5**: restyle.
- **A2**: put it and the charts it controls in one `st.container(border=True)`. A5–A7 ignore it today, but its position suggests it controls the whole tab.
- **G5**: hide.
- **D1, D2**: keep, with minor restyling.

## 4. Biggest payoff
1. **Theme-correct colour.** Add a theme-aware ramp, surface-relative borders and excluded-region fill, and a non-red `primaryColor`. One function and one config change fix dark-mode salience and the red clash on every tab.
2. **Map tab layout.** Short aligned control labels, no side column, one title and a horizontal colourbar. The map then lands in the first viewport at both 1440 and 900 px, and the slider misalignment goes away.
3. **Make the accuracy charts honest.** Clip the A7 axis, draw the main model on top, and replace the 8 number tiles with the split panel and the Δ chart. These charts carry the project's key result, and today they look broken or say nothing.

Files reviewed: `app.py` and `.streamlit/config.toml`, which has no `[theme]` or `[client]` section yet. Versions from `requirements.txt`: Streamlit 1.65.0, Plotly 7.1.0. No files were modified.
