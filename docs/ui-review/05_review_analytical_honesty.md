# Review: analytical honesty (independent subagent, verbatim)

## 1. Verdict
Every number the UI shows matches the result files and the README, and test and validation results are kept apart. The visuals still promise more than the results support. The Accuracy tab's per-region chart is broken by a −682 artefact. The map's colours are mostly the climatology pattern (base rate). The "latest forecast" reads as live. And the README's main caveat (beyond ~3 h every model is only 1–2 % better than climatology) is never stated in the UI: `app.py` contains no "1–2 %", "snapshot" or "official" wording.

## 2. Findings
| ID | Sev | Where | What could mislead and why | Recommendation | Effort |
|---|---|---|---|---|---|
| F1 | blocker | A7, `light_accuracy_all_3` | Zakarpattia shows skill −682. It had zero alerts in the test period, so its climatology Brier is 1e-8 and the ratio blows up. That one bar flattens the other 23, which hides that Chernihiv (−0.003) and Ivano-Frankivsk (−0.006) are worse than climatology and the rest range +0.006…+0.056. | Drop or annotate regions with no test alerts ("no alerts in test, skill undefined"), or plot the Brier difference instead. | S |
| F2 | major | M5/M6, `light_map_latest_1`, `light_map_replay_1` | The map looks like a confident regional forecast, but at the default h = 6 the latest forecast correlates 0.97 with climatology. "≥ 50 %" gives 4 regions for the model and 6 for climatology (latest), and 4 vs 4 in the replay. The replay also invites "4 forecast vs 13 happened", a threshold count set against outcomes. | Next to the map, show "at this horizon: X % better than climatology (test)". Replace the ≥ 50 % count with the expected number of regions (sum of p: 7.5 model / 7.9 climatology vs 13 actual). Add a "difference from climatology" view. | S–M |
| F3 | major | M1/M6/M9, default landing view | It looks live: the panel says "At this moment" and "the outcome is not known yet". The outcome is known, just not in the snapshot. Alerts still running at 05:05 UTC are missing from the dump, so "alert running now" at the 00:00 UTC issue time can be understated. | State: "Issued 12 Oct 03:00 Kyiv, at the end of the data snapshot. Not a live forecast." Mention the missing running alerts. Rename "At this moment". | S |
| F4 | major | A4/S3, `light_accuracy_*_1`, `light_sources_1` | The y-axes auto-scale to 0–0.03, so a 1.5 % gain fills the plot height above the zero line. The weak long-horizon skill is never put into words. | Add the sentence "beyond 3 h every model is 1–2 % better than the 28-day rate". Show the axis as "% better than climatology" and add an uncertainty band (main vs climatology, h ≥ 4: 0.014, 95 % day-bootstrap 0.007–0.021). | S |
| F5 | major | S2/S3 | Only test results are shown. There, alert-map beats alert-history at 17 of 21 horizons from 4 to 24 h (quiet), which looks like the main model drops the better source. The reason is on validation (8 of 21) and is invisible. The test gap is noise: +0.0015, CI −0.003…+0.006. | Show validation next to test, or as a toggle, labelled "used for the choice". | M |
| F6 | major | M5 legend, G2 | "P(alert)" is never defined as "an oblast-level alert in eTryvoga volunteer data". Donetsk shows 9 % on the latest map; official data has it under alert 99.8 % of hours, the volunteer data 27.9 % (agreement 28 %). The 19 % disagreement overall is not shown anywhere. | Define the target in the legend and caption, add one line on the disagreement, and note Donetsk. | S |
| F7 | minor | A3 | The default "All issue times" tile shows 0.258 with no hint that it comes mostly from an alert already running (12 % of next-hour cases). The quiet-moments value, 0.065, is one toggle away, and the tiles have no unit. | Show all and quiet side by side, with the unit "% better than climatology". | S |
| F8 | minor | S1/S2 | The tiles don't say "test" or which moments are scored; that is set on another tab. Three decimals invite ranking gaps that are noise: both channels vs alert-map is 0.003, while alert-map vs no Telegram at h = 1 (quiet) is +0.011, CI 0.004–0.020. | Label the period and subset on the tab itself. Add "gaps under ~0.01 are within day-to-day noise". | S |
| F9 | minor | A6 | Calibration has no reference line, and climatology is almost as well calibrated. The largest bin (80k rows) predicts 3.0 % against 5.7 % observed. | Add the climatology curve and show n per bin. | S |
| F10 | minor | G2 (also README line 7) | "Never seen in training" is not accurate: models are retrained every week, so later test weeks train on earlier test weeks. | "Each week forecast by a model trained only on earlier data." | S |
| F11 | minor | M8 | "Brier score now" is one hour across 24 regions, so it is noisy and easy to cherry-pick. "Now" actually means the target hour. | Rename to "Brier score for this hour" and add "see Accuracy for averages". | S |
| F12 | minor | M4/M9 (latest view) | Four model options silently show the main model, so a reader may conclude "Telegram changes nothing". | Disable those options in the latest view. | S |
| F13 | minor | D2; dark mode M5 | The weekly line's y-axis starts at 20 %, which exaggerates the rise. In dark mode the least likely regions are the brightest. | Start the axis at 0. Use a dark-surface ramp. | S |
| F14 | minor | S4 | The edited-posts exclusion is only in a caption on one tab. The validation drop from 0.032 to 0.027 (the evidence it mattered) is not shown. | Add one line with the comparison. | S |

## 3. What the UI must always show
- Every skill number labelled "vs climatology", with the period (test) and the subset (all or quiet) on the same screen.
- In words: next-hour skill comes mostly from alerts already running; beyond 3 h it is only 1–2 %.
- Beside the map: the test skill at the selected horizon.
- On the latest forecast: its issue time, "not live, end of data snapshot", and the missing still-running alerts.
- The target definition (volunteer, oblast-level), with the 19 % official disagreement.
- Edited posts excluded, and why.
- A noise scale (CI or "< 0.01 is noise") wherever models or sources are compared.
- Validation results wherever a choice was made on them.

## 4. Numeric discrepancies
None found. Checked:
- **Replay, 30 Sep 03:00, h = 11:** 13 alerts, 4 regions ≥ 50 %, Brier 0.263, +0.012 vs climatology.
- **Latest forecast, h = 6:** 4 regions ≥ 50 %.
- **Kyiv City chart:** first point 25 % model / 14 % climatology.
- **Next-hour tiles, all moments:** 0.258 / 0.258 / 0.263 / 0.111.
- **Next-hour tiles, quiet:** 0.065 / 0.054 / 0.068 / 0.041.
- **Sources tiles, quiet:** 0.054 / 0.059 / 0.065 / 0.068.
- **Overall table, main model, test:** Brier 0.1793, AUC 0.7653, skill 0.0253.
- **Quiet, 3 h ahead:** 0.022.

These all match `results/*.csv`, `predictions.parquet` and the README. One narrative mismatch: the README says Telegram features "add noise" beyond 3 h. That holds on validation; on test, alert-map is slightly but not significantly better there.

No repository files were changed.
