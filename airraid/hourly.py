"""Alert intervals -> hourly table and per-issue-time alert state (source-agnostic)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from airraid.regions import CODES


def cap_durations(alerts: pd.DataFrame, max_hours: float) -> pd.DataFrame:
    """Cut overlong alerts: past `max_hours` they are far more likely a missed all-clear than real."""
    out = alerts.copy()
    out["end_utc"] = out["end_utc"].clip(upper=out["start_utc"] + pd.Timedelta(hours=max_hours))
    return out


def hourly_matrix(alerts: pd.DataFrame, hours: pd.DatetimeIndex, covered_to: pd.Timestamp) -> pd.DataFrame:
    """1.0 if any alert overlaps hour [h, h+1), 0.0 otherwise, NaN for hours not fully observed."""
    alerts = alerts[(alerts["end_utc"] > hours[0]) & (alerts["start_utc"] < hours[-1] + pd.Timedelta(hours=1))]
    mat = np.zeros((len(hours) + 1, len(CODES)), dtype=np.int32)
    col = {c: i for i, c in enumerate(CODES)}
    i = hours.searchsorted(alerts["start_utc"].dt.floor("h"))
    j = np.maximum(hours.searchsorted(alerts["end_utc"].dt.ceil("h")), i + 1)
    k = alerts["region"].map(col).to_numpy()
    np.add.at(mat, (np.clip(i, 0, len(hours)), k), 1)
    np.add.at(mat, (np.clip(j, 0, len(hours)), k), -1)
    active = (np.cumsum(mat, axis=0)[:-1] > 0).astype(np.float32)
    active[hours + pd.Timedelta(hours=1) > covered_to] = np.nan
    return pd.DataFrame(active, index=hours, columns=list(CODES))


def ns(times: pd.Series) -> np.ndarray:
    """Tz-aware timestamps as int64 nanoseconds."""
    return pd.DatetimeIndex(times).as_unit("ns").asi8


def _merge(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(starts)
    starts, ends = starts[order], ends[order]
    ms, me = [starts[0]], [ends[0]]
    for s, e in zip(starts[1:], ends[1:]):
        if s <= me[-1]:
            me[-1] = max(me[-1], e)
        else:
            ms.append(s)
            me.append(e)
    return np.array(ms), np.array(me)


def alert_state(alerts: pd.DataFrame, times: pd.DatetimeIndex, cap_hours: float = 168.0) -> dict[str, pd.DataFrame]:
    """State at each issue time t, using only alerts that started before t.

    active_now: an alert is running at t; elapsed_h: how long it has run so far;
    since_start_h / since_end_h: hours since the last alert started / ended (0 while active).
    """
    t = times.as_unit("ns").asi8
    hour = 3_600_000_000_000
    out = {k: np.full((len(times), len(CODES)), np.nan, dtype=np.float32)
           for k in ("active_now", "elapsed_h", "since_start_h", "since_end_h")}
    for c, code in enumerate(CODES):
        g = alerts[alerts["region"] == code]
        if g.empty:
            out["active_now"][:, c], out["elapsed_h"][:, c] = 0, 0
            out["since_start_h"][:, c] = out["since_end_h"][:, c] = cap_hours
            continue
        s, e = _merge(ns(g["start_utc"]), ns(g["end_utc"]))
        idx = np.searchsorted(s, t, side="left") - 1  # last merged alert that started before t
        seen = idx >= 0
        si, ei = s[np.maximum(idx, 0)], e[np.maximum(idx, 0)]
        active = seen & (ei > t)
        out["active_now"][:, c] = active
        out["elapsed_h"][:, c] = np.where(active, (t - si) / hour, 0)
        out["since_start_h"][:, c] = np.where(seen, np.minimum((t - si) / hour, cap_hours), cap_hours)
        out["since_end_h"][:, c] = np.where(active, 0, np.where(seen, np.minimum((t - ei) / hour, cap_hours), cap_hours))
    return {k: pd.DataFrame(v, index=times, columns=list(CODES)) for k, v in out.items()}
