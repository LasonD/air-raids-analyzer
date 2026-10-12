"""Features at issue time t, built only from data published or observed before t.

This is the single place the core reads inputs. Every feature at t uses hours < t, alert
intervals that started before t, and signals published before t; tests/test_leakage.py
checks this by rebuilding features from data cut off at t and comparing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from airraid.config import Config
from airraid.hourly import alert_state, cap_durations, hourly_matrix, ns
from airraid.regions import BY_CODE, CODES
from airraid.schema import KIND_GROUPS, SourceData

ALERT_WINDOWS = (3, 24, 168, 672)
SIGNAL_WINDOWS = (1, 3, 6)
NATIONAL_WINDOWS = (3, 24)
GROUPS = sorted(set(KIND_GROUPS.values()))
HISTORY = pd.Timedelta(hours=max(ALERT_WINDOWS) + 48)
HOUR = pd.Timedelta(hours=1)


@dataclass
class Inputs:
    alerts: SourceData
    signals: list[SourceData]


@dataclass
class FeatureSet:
    region: pd.DataFrame       # one row per (issue time, region)
    hourly: pd.DataFrame       # hour x region alert matrix (labels come from here)


def _past(frame: pd.DataFrame, window: int, how: str, times: pd.DatetimeIndex) -> pd.DataFrame:
    """Aggregate over the `window` hours [t - window, t) for each issue time t."""
    roll = frame.rolling(window, min_periods=window)
    agg = roll.mean() if how == "mean" else roll.sum()
    return agg.shift(1).reindex(times)


def _signal_features(src: SourceData, hours: pd.DatetimeIndex, times: pd.DatetimeIndex,
                     exclude_edited: bool) -> dict[str, pd.DataFrame]:
    df = src.frame
    if exclude_edited:
        df = df[~df["edited"]]
    df = df.assign(group=df["kind"].map(KIND_GROUPS), hour=df["published_at_utc"].dt.floor("h"))
    df = df[df["hour"].isin(hours)]
    out: dict[str, pd.DataFrame] = {}
    regional = df.dropna(subset=["region"])
    for g in GROUPS:
        counts = (regional[regional["group"] == g].groupby(["hour", "region"]).size()
                  .unstack(fill_value=0).reindex(index=hours, columns=list(CODES), fill_value=0).astype(np.float32))
        for w in SIGNAL_WINDOWS:
            out[f"sig__{src.name}__{g}__{w}h"] = _past(counts, w, "sum", times)
        # Countrywide: each post counted once even if it names several regions.
        nat = (df[df["group"] == g].drop_duplicates(["ref", "published_at_utc"]).groupby("hour").size()
               .reindex(hours, fill_value=0).astype(np.float32))
        for w in NATIONAL_WINDOWS:
            col = _past(nat.to_frame("x"), w, "sum", times)["x"].to_numpy()
            out[f"sig__{src.name}__nat_{g}__{w}h"] = pd.DataFrame(np.repeat(col[:, None], len(CODES), 1),
                                                                   index=times, columns=list(CODES))
    # Hours since the region was last named in a threat post (capped at 48).
    threats = regional[regional["group"] != "clear"]
    since = np.full((len(times), len(CODES)), 48.0, dtype=np.float32)
    t = times.as_unit("ns").asi8
    for c, code in enumerate(CODES):
        pub = np.sort(ns(threats.loc[threats["region"] == code, "published_at_utc"]))
        if len(pub) == 0:
            continue
        idx = np.searchsorted(pub, t, side="left") - 1
        last = np.where(idx >= 0, pub[np.maximum(idx, 0)], np.iinfo(np.int64).min // 2)
        since[:, c] = np.minimum((t - last) / 3.6e12, 48.0)
    out[f"sig__{src.name}__since_threat_h"] = pd.DataFrame(since, index=times, columns=list(CODES))
    # Outside the source's coverage the features are unknown, not zero.
    max_lookback = pd.Timedelta(hours=max(max(SIGNAL_WINDOWS), max(NATIONAL_WINDOWS), 48))
    unknown = (times - max_lookback < src.covered_from) | (times > src.covered_to)
    for frame in out.values():
        frame.loc[unknown] = np.nan
    return out


def build(inputs: Inputs, times: pd.DatetimeIndex, cfg: Config) -> FeatureSet:
    alerts = cap_durations(inputs.alerts.frame, cfg.max_alert_hours)
    hours = pd.date_range(times[0] - HISTORY, times[-1] + pd.Timedelta(hours=max(cfg.horizons) + 1), freq="h")
    H = hourly_matrix(alerts, hours, inputs.alerts.covered_to)

    f: dict[str, pd.DataFrame] = dict(alert_state(alerts, times))
    for w in ALERT_WINDOWS:
        f[f"rate_{w}h"] = _past(H, w, "mean", times)
    nb = {c: list(BY_CODE[c].neighbours) for c in CODES}
    f["nb_active_now"] = pd.DataFrame({c: f["active_now"][nb[c]].sum(axis=1) for c in CODES})
    f["nb_rate_3h"] = pd.DataFrame({c: f["rate_3h"][nb[c]].mean(axis=1) for c in CODES})
    for name in ("active_now", "rate_3h", "rate_24h"):
        nat = f[name].mean(axis=1).to_numpy()
        f[f"nat_{name}"] = pd.DataFrame(np.repeat(nat[:, None], len(CODES), 1), index=times, columns=list(CODES))
    for src in inputs.signals:
        f.update(_signal_features(src, hours, times, cfg.exclude_edited))

    long = pd.DataFrame({k: v.reindex(index=times, columns=list(CODES)).to_numpy(np.float32).ravel()
                         for k, v in f.items()})
    long.insert(0, "region", np.tile(np.arange(len(CODES)), len(times)))
    long.insert(0, "t", np.repeat(times, len(CODES)))
    return FeatureSet(long, H)


def target_hour(t: pd.Series, h: pd.Series) -> pd.Series:
    """Horizon h = 1..24 is the hour [t + h - 1, t + h): h=1 is the hour right after issuing."""
    return t + pd.to_timedelta(h - 1, unit="h")


def expand(fs: FeatureSet, horizons: tuple[int, ...], sample: int | None = None, seed: int = 0) -> pd.DataFrame:
    """One row per (issue time, region, horizon) with target-hour features and the label y.

    The climatology and same-hour features read the same hour of day one or more days
    earlier (tau - 24 h <= t - 1 h for every horizon up to 24), i.e. a complete, observed hour.
    """
    reg = fs.region
    n = len(reg)
    if sample:
        rng = np.random.default_rng(seed)
        h = rng.choice(np.array(horizons), size=(n, sample))
        rows = np.repeat(np.arange(n), sample)
        h = h.ravel()
    else:
        rows = np.repeat(np.arange(n), len(horizons))
        h = np.tile(np.array(horizons), n)
    out = reg.iloc[rows].reset_index(drop=True)
    out["h"] = h.astype(np.int16)
    if max(horizons) > 24:
        raise ValueError("same-hour features assume horizons of at most 24 h")
    tau = target_hour(out["t"], out["h"])
    local = tau.dt.tz_convert("Europe/Kyiv")
    out["target_hour"] = local.dt.hour.astype(np.int16)
    out["target_dow"] = local.dt.dayofweek.astype(np.int16)

    H = fs.hourly
    clim = sum(H.shift(24 * j) for j in range(28)) / 28
    pos = H.index.get_indexer(tau)
    back = H.index.get_indexer(tau - pd.Timedelta(hours=24))
    col = out["region"].to_numpy()
    Hv, Cv = H.to_numpy(), clim.to_numpy()
    out["same_hour_prev"] = Hv[back, col]
    out["clim_28d"] = Cv[back, col]
    out["y"] = Hv[pos, col]
    return out


FEATURE_EXCLUDE = {"t", "y"}


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in FEATURE_EXCLUDE]
