"""The pipeline as separate stages, so the GUI can run them one by one at any replay moment.

`now` is the replay clock: everything computed for it starts from `known_at(inputs, now)`, the
data as it was known at that moment (the same cut-off tests/test_leakage.py checks). Models are
trained per week exactly as in backtest.run, so a replay reproduces the committed results.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from airraid.backtest import SHORT_HORIZON, _rows_between
from airraid.config import Config
from airraid.features import FeatureSet, Inputs, build, expand
from airraid.hourly import cap_durations, hourly_matrix
from airraid.models import Boosting
from airraid.regions import BY_CODE, CODES
from airraid.schema import SourceData
from airraid.sources import registry

HOUR = pd.Timedelta(hours=1)
SIGNALS = ("kpszsu", "povitryanatrivogaaa")  # feature column order as in the committed backtest


@dataclass(frozen=True)
class Settings:
    channels: tuple[str, ...] = ("povitryanatrivogaaa",)  # Telegram inputs used for 1-3 h ahead
    train_days: int = 182
    exclude_edited: bool = True
    max_alert_hours: float = 12.0

    def config(self) -> Config:
        return replace(Config(), train_days=self.train_days, exclude_edited=self.exclude_edited,
                       max_alert_hours=self.max_alert_hours)


def load_sources() -> Inputs:
    reg = registry()
    return Inputs(reg["etryvoga"].load(), [reg[s].load() for s in SIGNALS])


def known_at(inputs: Inputs, now: pd.Timestamp) -> Inputs:
    """The data as known at `now`: later alerts and posts disappear, a running alert has no end yet."""
    a = inputs.alerts.frame
    a = a[a["start_utc"] < now].copy()
    a.loc[a["end_utc"] > now, "end_utc"] = now + pd.Timedelta(days=365)
    alerts = replace(inputs.alerts, frame=a, covered_to=min(inputs.alerts.covered_to, now))
    signals = [replace(s, frame=s.frame[s.frame["published_at_utc"] < now], covered_to=min(s.covered_to, now))
               for s in inputs.signals]
    return Inputs(alerts, signals)


def weeks(cfg: Config) -> pd.DatetimeIndex:
    """Retraining moments: weekly from the start of the validation period to the end of the data."""
    return pd.date_range(cfg.val_start, cfg.data_end, freq=f"{cfg.retrain_days}D")


def week_of(cfg: Config, now: pd.Timestamp) -> pd.Timestamp:
    w = weeks(cfg)
    return w[w <= now][-1]


def features(inputs: Inputs, now: pd.Timestamp, s: Settings) -> FeatureSet:
    """Features for every issue time from the first training window up to `now`, from data known at `now`."""
    cfg = s.config()
    return build(known_at(inputs, now), pd.date_range(cfg.feature_start, now, freq="h"), cfg)


def train(fs: FeatureSet, s: Settings, channels: tuple[str, ...], week: pd.Timestamp) -> Boosting:
    """The model used during `week`: trained on issue times whose 24 hours all ended before it."""
    cfg = s.config()
    train_end = week - pd.Timedelta(hours=max(cfg.horizons))
    rows = _rows_between(fs, train_end - pd.Timedelta(days=cfg.train_days), train_end)
    X = expand(rows, cfg.horizons, sample=cfg.train_horizons_per_row, seed=cfg.seed).dropna(subset=["y"])
    assert X["t"].max() + pd.Timedelta(hours=max(cfg.horizons)) <= week
    return Boosting(channels, cfg.seed).fit(X, X["y"])


def predict(fs: FeatureSet, s: Settings, short: Boosting | None, long: Boosting,
            start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Forecasts issued in [start, end); y is NaN where the hour is not known yet."""
    X = expand(_rows_between(fs, start, end), s.config().horizons)
    out = X[["t", "region", "h", "y", "active_now"]].copy()
    out["p_climatology"] = X["clim_28d"].to_numpy()
    out["p_long"] = long.predict(X)
    out["p_short"] = short.predict(X) if short is not None else out["p_long"]
    out["p_main"] = out["p_short"].where(out["h"] <= SHORT_HORIZON, out["p_long"])
    return out


def scoring_weeks(cfg: Config, now: pd.Timestamp, n: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """The last `n` weekly blocks of issue times whose 24 hours are all known at `now`."""
    last = now - pd.Timedelta(hours=max(cfg.horizons)) + HOUR  # exclusive end
    return [(w, min(w + pd.Timedelta(days=cfg.retrain_days), last)) for w in weeks(cfg) if w < last][-n:]


# ---------------------------------------------------------------- patterns (data known at `now`)

def hourly_history(alerts: SourceData, now: pd.Timestamp, max_alert_hours: float) -> pd.DataFrame:
    """Hour x region alert table from the first full month of data up to `now`."""
    a = known_at(Inputs(alerts, []), now).alerts
    hours = pd.date_range(pd.Timestamp("2022-03-01", tz="UTC"), now, freq="h", inclusive="left")
    return hourly_matrix(cap_durations(a.frame, max_alert_hours), hours, a.covered_to)


def persistence(H: pd.DataFrame, max_h: int = 24) -> pd.DataFrame:
    """Chance of an alert h hours later minus that region's usual chance, after an alert hour or a quiet
    one, averaged over regions. Within-region, so front-line regions being busier does not count."""
    A = H.to_numpy()
    rows = []
    for h in range(1, max_h + 1):
        after_alert, after_quiet = [], []
        for r in range(A.shape[1]):
            now, later = A[:-h, r], A[h:, r]
            ok = ~(np.isnan(now) | np.isnan(later))
            now, later = now[ok], later[ok]
            if min((now == 1).sum(), (now == 0).sum()) < 50:
                continue
            after_alert.append(later[now == 1].mean() - later.mean())
            after_quiet.append(later[now == 0].mean() - later.mean())
        rows.append({"h": h, "after_alert": np.mean(after_alert), "after_quiet": np.mean(after_quiet)})
    return pd.DataFrame(rows)


def durations(alerts: SourceData, now: pd.Timestamp) -> pd.DataFrame:
    """Alerts that had ended by `now`, with their length in hours."""
    a = alerts.frame[alerts.frame["end_utc"] <= now]
    return a.assign(hours=(a["end_utc"] - a["start_utc"]).dt.total_seconds() / 3600)


def neighbour_correlation(H: pd.DataFrame) -> tuple[float, float]:
    """Average correlation of hourly alert series between neighbouring and between other regions."""
    C = H.dropna().corr().to_numpy()
    nb, other = [], []
    for i, a in enumerate(CODES):
        for j, b in enumerate(CODES):
            if i < j and not np.isnan(C[i, j]):
                (nb if b in BY_CODE[a].neighbours else other).append(C[i, j])
    return float(np.mean(nb)), float(np.mean(other))
