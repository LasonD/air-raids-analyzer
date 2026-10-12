"""Command line: python -m airraid {fetch,snapshot,context,backtest,forecast,report,gui}."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import webbrowser
from dataclasses import replace

import pandas as pd

from airraid import backtest, evaluate, paths, uncertainty
from airraid.config import Config
from airraid.hourly import cap_durations, hourly_matrix
from airraid.schema import KINDS
from airraid.sources import registry
from airraid.paths import RAW
from airraid.sources.telegram import DROP

RESULTS = paths.RESULTS


def cmd_fetch(cfg: Config, args) -> None:
    for name in (cfg.target, *cfg.signals):
        print(f"fetching {name} ...")
        registry()[name].fetch()


def cmd_context(cfg: Config, args) -> None:
    """Source health and the 2026 hourly alert table, for the GUI's Sources and Data tabs."""
    RESULTS.mkdir(exist_ok=True)
    reg = registry()
    alerts = reg[cfg.target].load()
    health = [{"source": alerts.name, "role": "alerts (target)", "covered_from": str(alerts.covered_from),
               "covered_to": str(alerts.covered_to), "records": len(alerts.frame)}]
    for name in cfg.signals:
        if not any((RAW / "telegram" / name).glob("*.html.gz")):  # fresh clone: only the snapshot exists
            d = reg[name].load()
            health.append({"source": name, "role": "signals (snapshot)", "covered_from": str(d.covered_from),
                           "covered_to": str(d.covered_to), "records": len(d.frame)})
            continue
        posts = reg[name].classified_posts()
        threat = posts["kind"].isin(KINDS) & (posts["kind"] != "clear")
        daily = posts.set_index("published_at_utc").resample("D").size()
        health.append({"source": name, "role": "signals", "covered_from": str(posts["published_at_utc"].min()),
                       "covered_to": str(posts["published_at_utc"].max()), "records": len(posts),
                       "kept_posts": int((posts["kind"] != DROP).sum()),
                       "threat_posts_with_region": f"{(posts.loc[threat, 'regions'].str.len() > 0).mean():.1%}",
                       "edited_posts": f"{posts['edited'].mean():.1%}", "days_under_50_posts": int((daily < 50).sum())})
    (RESULTS / "source_health.json").write_text(json.dumps(health, indent=2))
    hours = pd.date_range(pd.Timestamp("2026-01-01", tz="UTC"), cfg.data_end, freq="h", inclusive="left")
    H = hourly_matrix(cap_durations(alerts.frame, cfg.max_alert_hours), hours, alerts.covered_to)
    H.to_parquet(RESULTS / "hourly_alerts.parquet")
    print(pd.DataFrame(health).to_string(index=False))


def cmd_snapshot(cfg: Config, args) -> None:
    """Commit-able parsed Telegram events (no text), so results can be reproduced after posts change."""
    for name in cfg.signals:
        print(f"{name}: {registry()[name].save_snapshot()}")


def cmd_backtest(cfg: Config, args) -> None:
    RESULTS.mkdir(exist_ok=True)
    cmd_context(cfg, args)
    pred = backtest.run(cfg)
    _save_predictions(pred, _suffix(cfg))
    cmd_report(cfg, args, pred=pred)


def cmd_forecast(cfg: Config, args) -> None:
    RESULTS.mkdir(exist_ok=True)
    fc = backtest.latest_forecast(cfg)
    fc.to_parquet(RESULTS / "forecast_latest.parquet", index=False)
    print(f"forecast issued at {fc['t'].iat[0]} (main model) -> results/forecast_latest.parquet")


def _suffix(cfg: Config) -> str:
    return "" if cfg.exclude_edited else "_with_edited"


def _save_predictions(pred: pd.DataFrame, suffix: str) -> None:
    small = pred.astype({c: "float32" for c in pred.columns if c.startswith("p_")} | {"y": "int8", "active_now": "int8"})
    small.to_parquet(RESULTS / f"predictions{suffix}.parquet", index=False, compression="zstd")


def cmd_report(cfg: Config, args, pred: pd.DataFrame | None = None) -> None:
    suffix = _suffix(cfg)
    if pred is None:
        pred = pd.read_parquet(RESULTS / f"predictions{suffix}.parquet")
        if "p_main" not in pred:
            pred = backtest.add_main_model(pred)
            _save_predictions(pred, suffix)
    overall = evaluate.summary(pred, ["period"])
    test = pred[pred["period"] == "test"]
    # "Quiet" = no alert running at the issue time: the honest question of whether a new one starts.
    quiet = test[test["active_now"] == 0]
    overall = pd.concat([overall, evaluate.summary(quiet).assign(period="test, quiet at t")], ignore_index=True)
    overall.to_csv(RESULTS / f"metrics_overall{suffix}.csv", index=False)
    evaluate.summary(test, ["h"]).to_csv(RESULTS / f"metrics_by_horizon{suffix}.csv", index=False)
    evaluate.summary(quiet, ["h"]).to_csv(RESULTS / f"metrics_by_horizon_quiet{suffix}.csv", index=False)
    evaluate.region_names(evaluate.summary(pred[pred["period"] == "test"], ["region"])).to_csv(
        RESULTS / f"metrics_by_region{suffix}.csv", index=False)
    meta = {"main_model": f"alert-map for h<={backtest.SHORT_HORIZON}, alert history after", "data_end": str(cfg.data_end), "val_start": str(cfg.val_start), "test_start": str(cfg.test_start),
            "train_days": cfg.train_days, "retrain_days": cfg.retrain_days, "exclude_edited": cfg.exclude_edited}
    (RESULTS / f"run{suffix}.json").write_text(json.dumps(meta, indent=2))
    if not suffix:  # 95 % ranges for the main results (day-level bootstrap)
        uncertainty.bootstrap(pred).to_csv(RESULTS / "uncertainty.csv", index=False)
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(overall.round(4).to_string(index=False))


def cmd_gui(cfg: Config, args) -> None:
    """Start the Streamlit GUI with this interpreter, so the same command works on every OS.

    Headless mode skips Streamlit's first-run e-mail prompt; the browser is opened from here instead.
    """
    if not args.no_browser:
        threading.Timer(3, webbrowser.open, ["http://localhost:8501"]).start()
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(paths.ROOT / "app.py"), "--server.headless=true"],
                   cwd=paths.ROOT, check=True)


def main() -> None:
    p = argparse.ArgumentParser(prog="airraid")
    p.add_argument("command", choices=["fetch", "snapshot", "context", "backtest", "forecast", "report", "gui"])
    p.add_argument("--include-edited", action="store_true",
                   help="keep edited Telegram posts (comparison run; their edit time is unknown)")
    p.add_argument("--no-browser", action="store_true", help="gui: do not open a browser tab")
    args = p.parse_args()
    cfg = replace(Config(), exclude_edited=not args.include_edited)
    {"fetch": cmd_fetch, "context": cmd_context, "backtest": cmd_backtest, "forecast": cmd_forecast,
     "report": cmd_report, "gui": cmd_gui, "snapshot": cmd_snapshot}[args.command](cfg, args)
