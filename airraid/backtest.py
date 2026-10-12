"""Walk-forward evaluation: retrain weekly, predict the next week, never train on its labels."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from airraid.config import Config
from airraid.features import FeatureSet, Inputs, build, expand
from airraid.models import BASELINES, Boosting, Logistic
from airraid.sources import registry

# Source sets compared; "none" = alert history only.
SOURCE_SETS = {
    "none": (),
    "kpszsu": ("kpszsu",),
    "alertmap": ("povitryanatrivogaaa",),
    "both": ("kpszsu", "povitryanatrivogaaa"),
}
# Chosen on the validation weeks (best Brier skill at all 24 horizons); the test period was not used.
MAIN_MODEL = "alertmap"


def load_inputs(cfg: Config, signals: tuple[str, ...] | None = None) -> Inputs:
    reg = registry()
    return Inputs(reg[cfg.target].load(), [reg[s].load() for s in (signals or cfg.signals)])


def _rows_between(fs: FeatureSet, start: pd.Timestamp, end: pd.Timestamp) -> FeatureSet:
    reg = fs.region
    return FeatureSet(reg[(reg["t"] >= start) & (reg["t"] < end)], fs.hourly)


def run(cfg: Config, source_sets: dict[str, tuple[str, ...]] = SOURCE_SETS, log=print) -> pd.DataFrame:
    """Predictions for every validation and test week, all models, all horizons."""
    inputs = load_inputs(cfg)
    times = pd.date_range(cfg.feature_start, cfg.data_end - pd.Timedelta(hours=1), freq="h")
    t0 = time.time()
    fs = build(inputs, times, cfg)
    log(f"features: {len(fs.region)} region-hours x {fs.region.shape[1]} columns ({time.time() - t0:.0f}s)")

    out = []
    weeks = pd.date_range(cfg.val_start, cfg.data_end, freq=f"{cfg.retrain_days}D", inclusive="left")
    for w in weeks:
        # Train on issue times whose 24 horizons all ended before w: no label from the predicted week.
        train_end = w - pd.Timedelta(hours=max(cfg.horizons))
        train = expand(_rows_between(fs, train_end - pd.Timedelta(days=cfg.train_days), train_end),
                       cfg.horizons, sample=cfg.train_horizons_per_row, seed=cfg.seed)
        train = train.dropna(subset=["y"])
        test = expand(_rows_between(fs, w, min(w + pd.Timedelta(days=cfg.retrain_days), cfg.data_end)), cfg.horizons)
        test = test.dropna(subset=["y"]).reset_index(drop=True)
        assert train["t"].max() + pd.Timedelta(hours=max(cfg.horizons)) <= w

        # active_now lets the report separate "alert already running" from "will a new one start".
        pred = test[["t", "region", "h", "y", "active_now"]].copy()
        pred["period"] = "test" if w >= cfg.test_start else "validation"
        for name, fn in BASELINES.items():
            pred[f"p_{name}"] = fn(test)
        pred["p_logistic"] = Logistic().fit(train, train["y"]).predict(test)
        for name, srcs in source_sets.items():
            t1 = time.time()
            pred[f"p_gbm_{name}"] = Boosting(srcs, cfg.seed).fit(train, train["y"]).predict(test)
            log(f"week {w:%Y-%m-%d} ({pred['period'].iat[0]}): gbm_{name} on {len(train)} rows ({time.time() - t1:.0f}s)")
        out.append(pred)
    return pd.concat(out, ignore_index=True)


def latest_forecast(cfg: Config, sources: tuple[str, ...]) -> pd.DataFrame:
    """Train on everything labelled and forecast the 24 hours after the end of the data."""
    inputs = load_inputs(cfg)
    issue = cfg.data_end
    times = pd.date_range(issue - pd.Timedelta(days=cfg.train_days), issue, freq="h")
    fs = build(inputs, times, cfg)
    train_end = issue - pd.Timedelta(hours=max(cfg.horizons))
    train = expand(_rows_between(fs, times[0], train_end), cfg.horizons, sample=cfg.train_horizons_per_row,
                   seed=cfg.seed).dropna(subset=["y"])
    now = expand(_rows_between(fs, issue, issue + pd.Timedelta(hours=1)), cfg.horizons)
    model = Boosting(sources, cfg.seed).fit(train, train["y"])
    out = now[["t", "region", "h"]].copy()
    out["p"] = model.predict(now)
    out["p_climatology"] = now["clim_28d"].to_numpy()
    return out
