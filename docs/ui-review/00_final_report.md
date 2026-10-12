# UI review: final report

**Inputs:** the inventory ([01_inventory.md](01_inventory.md), 32 screenshots in light and dark mode and
at a narrow width) and four independent reviews. Each reviewer looked at one aspect only, read-only, and
did not see the other reviews:

| File | Aspect | Code |
|---|---|---|
| [02](02_review_first_time_viewer.md) | First-time comprehension | FTV |
| [03](03_review_structure_redesign.md) | Structure and redesign | IA |
| [04](04_review_visual_design.md) | Visual design and charts | VIS |
| [05](05_review_analytical_honesty.md) | Analytical honesty | HON |

This report merges their findings, checks their claims against the code and data, records where they
disagree and decides each disagreement.

## Verdict

The pieces are right and every displayed number is correct (HON checked 12 against the result files).
The app fails the owner's test of being "immediately known what it is, what it does, what the sources
are, and what we can do with it":

- The app never says it is a **fixed snapshot, not a live or official warning service** (blocker).
- It never says **how good the forecast is**.
- It never says **where the data comes from** beyond two Telegram handles.
- It shows the model's internals (673 issue times × 24 hours ahead × 6 models) instead of the visitor's
  questions.
- One chart is **visibly broken**: Zakarpattia shows −682.

These are structural problems, not cosmetic ones, so the fix is a restructure around the visitor's
questions, not more labels.

## Reviewer claims I verified

| Claim | Check | Result |
|---|---|---|
| A7: Zakarpattia skill −682 | `metrics_by_region.csv`, test alert share | ✔ 0 alert hours in the test period, so skill is undefined. Also: **Ivano-Frankivsk AUC 0.32** and Chernihiv −0.003, both worse than climatology, are hidden by that bar. |
| Expected vs actual, 30 Sep 03:00, 11 h ahead | sum of `p_main` | ✔ 7.5 expected, 13 actual |
| The latest map ≈ the daily rhythm | correlation between model and climatology at 6 h ahead | ✔ 0.973 |
| Telegram helps the next hour (quiet moments) | own day-block bootstrap | ✔ +0.011, 95 % range +0.003 to +0.018 |
| Beyond 3 h, Telegram gain is noise (test) | same | ✔ +0.0015, range −0.003 to +0.006 |
| Main model beats climatology at 4–24 h | same | ✔ +0.014, range +0.007 to +0.022 |
| "Never seen in training" is inaccurate | backtest design | ✔ Weekly retraining means later test weeks train on earlier test weeks. The correct wording is "each week forecast by a model trained only on earlier data". The same wording is in the README. |
| The README says Telegram "adds noise" beyond 3 h | validation vs test | ✔ True on validation only; on test it is neutral. The README needs a fix. |
| Proposed Streamlit features exist (1.65) | introspection | ✔ `st.fragment`, `st.pills`, `st.segmented_control`, map click via `on_select`, `st.context.theme`, `[theme.light]`/`[theme.dark]`, `client.toolbarMode` |

## Consensus findings, ranked

"Raised by" counts independent reviewers. My own inventory items are marked INV.

| # | Finding | Raised by | Severity | Fix |
|---|---|---|---|---|
| 1 | Region skill chart (A7) broken by Zakarpattia (−682); real weak regions hidden | FTV, IA, VIS, HON | blocker | Exclude regions with no test alerts (with a note), clip the axis, show weak regions honestly |
| 2 | App does not say it is a snapshot, not live, not official; the latest forecast reads as "now" | FTV, HON, IA | blocker | Status banner: data until 12 Oct 03:00 Kyiv, research prototype, not a warning service, follow official alerts |
| 3 | App never states the findings (how good, where it fails) | FTV, HON, IA | blocker | Three plain findings with uncertainty in the header |
| 4 | Sources are not explained (what they are, their roles, the target definition, the 19 % official disagreement) | FTV, HON, IA | major | Source cards plus a target definition |
| 5 | Raw skill decimals without unit or reference; jargon (Brier skill, horizon, climatology, quiet, issued) | FTV, VIS, HON, IA | major | "% better than the usual daily rhythm" everywhere; one glossary |
| 6 | Map controls: 673-step slider, 6-model radio, wrapped label misaligning the sliders, target hour stated three times | FTV, VIS, IA, INV | major | Mode presets + date/hour pickers, short aligned labels, one sentence naming the moment and the hour |
| 7 | "Regions ≥ 50 %" is an arbitrary threshold set against an actual count | FTV, VIS, HON, IA | major | Expected regions under alert (sum of p) vs actual |
| 8 | "Brier score now" for one hour: noisy, jargon, red pill | FTV, VIS, HON, IA | major | Cut from the map view (averages live in the evidence section) |
| 9 | Dark mode: lowest probabilities and excluded regions brightest; Streamlit's red accent clashes with "red = alert" | VIS, HON, INV | major | Theme-aware ramp and borders; blue or neutral `primaryColor` |
| 10 | Main model hidden under another line; climatology drawn twice | VIS | major | Main on top and thicker; zero line labelled "usual daily rhythm" |
| 11 | Telegram evidence = 4 crossing lines, test only; the validation reason for the choice is invisible; no noise scale | VIS, HON, IA | major | Δ vs no-Telegram, validation and test side by side, with 95 % range |
| 12 | One tab's control silently changes another tab | FTV, VIS, IA | minor | No cross-tab state (all and quiet shown together) |
| 13 | Raw tables (column names, "None", timestamps) | FTV, VIS, IA | minor | Expanders, readable labels, formatted dates |
| 14 | Page greys out and shows stale values on every change | INV, IA | minor | `st.fragment` around the explorer |
| 15 | Red outlines merge into a mesh in big waves | VIS | minor | Halo outline (surface-coloured underlay) |
| 16 | Calibration chart has no climatology reference | HON, VIS | minor | Add climatology curve, n per bin, equal axes |
| 17 | Weekly chart axis starts at 20 %; partial weeks | FTV, VIS, HON | minor | Axis from 0, drop partial weeks |
| 18 | Streamlit chrome (Deploy button, Plotly toolbars) | all | minor | `toolbarMode="viewer"`, `displayModeBar=False` |

## Where reviewers disagreed, and my call

| Question | Positions | Decision |
|---|---|---|
| Tabs or one page | FTV: rename tabs to questions. IA: one page, sections = questions | **One page, four question sections, anchor links at the top.** The four questions get answered without clicking; detail goes into expanders so the page stays short. |
| Model choice on the map | FTV: remove. IA: Forecast \| Baseline. HON: add a "difference from climatology" view | **Forecast \| Usual daily rhythm toggle.** Flipping it makes the 0.97 similarity visible, which is honest and needs no extra view. Other models only in the evidence section. |
| Hours-ahead control | IA: in-browser animation slider with ▶. Others: plain slider | **Plain slider inside `st.fragment` now; animation only if time remains.** 24 choropleth frames with outlines is the riskiest item. |
| Accuracy chart form | VIS: split panel (dots + lines). IA: main model, all and quiet lines. HON: add uncertainty band | **One chart: main model, "% better than the usual daily rhythm" by hours ahead, all and quiet lines, with 95 % day-bootstrap band.** Other models in a table in an expander. |
| Telegram evidence | VIS: Δ lines. IA: Δ bars per channel. HON: validation next to test, plus noise | **Δ vs no Telegram (quiet moments), validation and test side by side, with 95 % range.** That shows both why the choice was made and that the effect is real but short-lived. |
| Example moments ("presets") | IA proposes Biggest attack / Quiet night / A hit / A miss. HON warns about cherry-picking | **Yes, always a hit and a miss together**, with the selection rule written next to them. |
| Effort | IA: 9–10 h total | About 6 h remain, including README and submission. **Phase 1 (~3 h) only**; phase 2 if time allows. |

## What I would not do now

- **Animated 24-frame map:** high effort, high risk. The plain slider is enough once it no longer greys the page.
- **Region skill as a choropleth:** the fixed bar chart says the same.
- **Click-to-select a region on the map:** nice, but the selectbox works. Phase 2.
- **Showing all 7 models in the explorer:** belongs in the evidence table.

## Action plan

### Phase 1 (tonight, about 3 h, in this order)

1. **Correctness first (30 min).**
   - Fix A7.
   - Fix the README wording ("never seen in training"; "adds noise" holds on validation only).
   - Compute 95 % day-bootstrap ranges into `results/` with a script, so the UI and README can cite them.
2. **Header that answers the four questions (30 min).**
   - One-sentence "what it is".
   - Status banner (snapshot until 12 Oct 03:00 Kyiv; not live; not a warning service).
   - Three findings in plain %, with ranges.
   - A sources line with links.
3. **Explorer (75 min).**
   - Mode pills: Latest · Biggest attack · Quiet night · A hit · A miss · Pick date and hour.
   - Short aligned labels.
   - One sentence naming the forecast moment and the target hour.
   - Forecast \| Usual daily rhythm toggle.
   - Expected vs actual regions, and the test skill at the selected hours ahead.
   - Cut M3, M6, M8 and M9; M13 into an expander; wrap everything in `st.fragment`.
4. **Theme (20 min).**
   - Blue or neutral `primaryColor`.
   - Theme-aware ramp, borders and excluded-region fill.
   - Hide the toolbar and Plotly mode bars.
5. **"How good is it?" section (45 min).**
   - The accuracy chart with all and quiet lines and a range band.
   - The Telegram Δ chart, validation and test.
   - Calibration with a climatology reference.
   - Region bars, fixed.
   - Tables in expanders with readable labels.
6. **"Where does the data come from?" and "How was it tested, and limits" (30 min).**
   - Source cards and the target definition, with the official disagreement (Donetsk example).
   - Edited-posts exclusion, with its validation numbers.
   - Leakage safeguards and limitations, short.
7. **Verify (20 min).** Playwright in light, dark and narrow; screenshots; README.

### Phase 2 (only if time remains)

Animated hours slider; click-to-select region; red outline halo; partial weeks in the weekly chart.

## Outcome (Phase 1 implemented)

Screenshots after the change: [after/](after/). Checked with Playwright in light, dark and 900 px
width, every preset and "Pick a date"; no errors.

| # | Status |
|---|---|
| 1 | Region chart: Zakarpattia left out with a note; negative regions shown in grey |
| 2, 3 | Header: what it is, snapshot banner, three findings with 95 % ranges, sources with links |
| 4 | "Where does the data come from?": three source cards, target definition, official disagreement |
| 5 | "% better than the usual daily rhythm" everywhere; glossary at the end |
| 6, 7, 8 | Explorer: presets + date/hour pickers, short aligned controls, one sentence, expected vs actual, test skill at the chosen hours ahead; old M3/M6/M8/M9 removed |
| 9 | Theme-aware ramp, borders and excluded fill; blue accent; toolbars hidden |
| 10, 11 | Accuracy chart (next hour + 2–24 h, all and quiet, bands); Telegram gain, validation vs test, with switch-point marker |
| 12, 13, 14 | One page, no cross-tab state; tables in expanders with readable labels; explorer in `st.fragment` |
| 15, 16, 17 | Halo outline; calibration with climatology, equal axes; weekly chart from 0, whole weeks only |
| README | "Never seen in training" and "adds noise" corrected; 95 % ranges added (`results/uncertainty.csv`) |

Not done (phase 2): animated hours slider, click-to-select region.
