# Review: first-time comprehension (independent subagent, verbatim)

## 1. Verdict
The title and the core visual work: blue fill for the forecast and a red outline for "an alert happened" can be read in seconds. But a first-time visitor can't answer "is this live?", "how good is it?" or "where does the data come from?" within 30 seconds. Those answers are in the README, in grey captions or behind jargon. The landing view is a forecast with no outcome to compare against, a list of six unexplained models and an arbitrary "≥ 50 %" count, so the strongest evidence (a replay with red outlines, plus the headline result) is hidden behind the far end of a slider and a tab of raw Brier-skill decimals.

## 2. Findings
| ID | Sev | Where | Problem for a first-time user | Recommendation | Effort |
|---|---|---|---|---|---|
| F1 | blocker | G2, M9; light_map_latest_1 | Nothing says the app is a fixed snapshot rather than live or official. "Latest forecast… outcome not known yet" reads as live, and a member of the public could act on it. | Banner under the title: "Snapshot: data up to Mon 12 Oct 03:00 Kyiv. Research prototype, not a warning service. Follow official alerts." | S |
| F2 | blocker | whole app | The app never says how good the forecast is. The README's key findings don't appear anywhere in it. | Three plain bullets under the title: next hour 26 % better than the baseline (6 % when no alert is running); 4–24 h only 1–2 % better; Telegram helps for 1–3 h only. | S |
| F3 | blocker | A7; light_accuracy_quiet_3 | Zakarpattia shows −682 because it had zero alerts in the test period, so the skill is undefined (its Brier score is ~0, i.e. near-perfect). That bar squashes every other bar to nothing, so the chart reads as a catastrophic failure. | Leave out regions with no alerts and add a note, clip the axis, and label the values. | S |
| F4 | major | G3, M1; light_map_latest_1 | The tab is called "Map replay" but opens on a forecast that isn't a replay. Replay mode is just the rest of a 673-position slider, and nothing invites the user to drag it. | An explicit toggle "Latest forecast / Replay a past day (see what happened)", plus a one-line hint. | M |
| F5 | major | M2, M3, M5 title | Two controls, a caption and the map title each restate the target hour, so the user has to do the "issued + h" arithmetic. | One sentence above the map: "Forecast made Mon 12 Oct 03:00 for 08:00–09:00 (6 h ahead)". Shorten the labels. | S |
| F6 | major | M4 | Six models appear on the landing screen. "Both channels" and "No Telegram" mean nothing yet, and 4 of the 6 do nothing in latest mode. | Remove from the map; default to the main model. Offer a "compare with baseline" toggle at most. | S |
| F7 | major | M6, M7; light_map_replay_1 | "≥ 50 %: 4" next to "alerts: 13" suggests 9 misses. For a probabilistic forecast that is the wrong comparison. | "Expected regions under alert: 7.5 · Actual: 13" (the sum of the shown probabilities). | S |
| F8 | major | M8 | "Brier score now 0.263 ↑ +0.012" in red: jargon, "now" is wrong in replay, and you have to re-read to work out the sign. | Cut it, or replace with "This hour: slightly worse than baseline". | S |
| F9 | major | A1, A3, A4, S2, S3 | Raw skill decimals (0.258, 0.015) carry no meaning. "Horizon", "h = 1", "climatology" and "issue time" are never defined. | Show "% better than baseline". Call the baseline "usual daily rhythm (region's alert share at this hour, last 28 days)" and define it once. Add a glossary expander. | S–M |
| F10 | major | A3 (quiet) | "Both channels" (0.068) beats "Main" (0.065), with no explanation on this tab. | One line: "Main model fixed on the validation weeks; switching after seeing the test would be leakage." | S |
| F11 | major | G3, S1–S5 | The "Sources" tab never says what the sources are. It opens with an ablation chart, and the only source description anywhere is two Telegram handles in a grey caption. | Open with source cards: name and link, what it is, role (target vs signal), period, post count, and the official vs volunteer caveat. Then "Does Telegram help?" with its conclusion as the chart title. | M |
| F12 | minor | A2, S4 | "Moments scored" silently changes the Sources tab, but not A5–A7. | Put the scope in each chart title, or repeat the control on each tab. | S |
| F13 | minor | A5, S5 | Raw tables: `log_loss`, `n`, `days_under_50_posts`, "None", "+00:00". | Collapse into an expander, rename columns, format dates. | S |
| F14 | minor | D1, D2 | No takeaway, no link to the baseline. The weekly chart's y-axis starts at 20 %. | Put the finding in the title ("this daily rhythm is the baseline to beat"). Start the axis at 0. | S |
| F15 | minor | M11–M13 | The region picker sits below the map, disconnected from it. M13 is dense, and the legend says "Main: alert-map for 1-3 h, history after". | Legend "Forecast / Baseline". Put M13 in an expander. Optionally select a region by clicking the map. | S/M |
| F16 | minor | G5 | The "Deploy" button and menu add noise. | `client.toolbarMode = "viewer"` | S |

## 3. Per-element verdicts
- **G2:** reword into a two-line intro, the snapshot banner (F1), the result bullets (F2) and linked sources.
- **G3:** rename the tabs to the questions they answer: "Forecast map", "How accurate?", "Does Telegram help?", "Alert patterns".
- **G5:** hide.
- **M3:** cut; merge into the one sentence above the map (F5).
- **M4:** move to the Sources tab or behind an expander.
- **M6:** reword to expected vs actual count.
- **M8:** cut.
- **M9:** fold into the global banner.
- **M13:** put behind an expander.
- **A3:** reword as % better, and add the note on how the main model was chosen.
- **A5:** put behind an expander.
- **A7:** fix (exclude zero-alert regions, clip the axis).
- **S2:** merge with A3 (it is the same kind of tile row) or fold into the S3 chart.
- **S4:** move the conclusion into the S3 title and drop the note about the other tab.
- **S5:** turn into source cards and move to the top of the tab.

**Works well, keep:** the title; the red outline over blue fill; the calibration title phrased as a question; the explanation of the grey regions; the "map hour" box linking the charts to the map; Kyiv time throughout.

## 4. The three changes that would help most
1. **A header that answers the four questions.** What it is, its status (fixed snapshot of 12 Oct 03:00, not live, not official), three plain-% result bullets, and linked sources.
2. **A map tab that explains itself.** An explicit Latest/Replay toggle with an invitation to replay, one sentence naming the forecast moment and target hour, no model radio, and expected vs actual counts.
3. **Scores in plain language.** "% better than the usual daily rhythm" everywhere, the region chart fixed, raw tables collapsed, and each chart titled with its conclusion.

The reviewer modified no files. Its two numbers came from read-only queries on `results/`:
- **Zakarpattia:** `metrics_by_region.csv` gives Brier 0.000007, skill −681.75 and AUC NaN, meaning no alerts in the test period.
- **Expected vs actual count:** the 30 Sep 03:00 replay at 11 h ahead has probabilities summing to 7.5, against 13 regions that actually had an alert.

**Side note:** the latest map and the 30 Sep replay map look almost identical, because the fill mostly reflects each region's usual alert level. A first-time user dragging the slider may think nothing is changing. A one-line note would help.
