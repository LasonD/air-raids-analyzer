"""Internal data format. Source adapters produce it; the core consumes only this.

Alerts:  one row per alert interval    -> region, start_utc, end_utc, end_estimated
Signals: one row per (post, region)    -> published_at_utc, region (None = not tied to a region),
                                          kind, ref, edited
Each source also reports the period it covers, so "no data" is never mistaken for "quiet".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from airraid.regions import CODES

ALERT_COLUMNS = ["region", "start_utc", "end_utc", "end_estimated"]
SIGNAL_COLUMNS = ["published_at_utc", "region", "kind", "ref", "edited"]

KINDS = ("drone", "jet_drone", "missile", "ballistic", "guided_bomb", "aviation", "explosion", "clear")
# Coarse groups the features are built on; most fine kinds would be near-empty columns.
KIND_GROUPS = {
    "drone": "drone", "jet_drone": "drone",
    "missile": "missile", "ballistic": "missile",
    "guided_bomb": "aviation", "aviation": "aviation",
    "explosion": "explosion",
    "clear": "clear",
}


@dataclass(frozen=True)
class SourceData:
    name: str
    role: Literal["alerts", "signals"]
    frame: pd.DataFrame
    covered_from: pd.Timestamp  # data is complete inside [covered_from, covered_to)
    covered_to: pd.Timestamp


def _check_utc(s: pd.Series, col: str) -> None:
    if not isinstance(s.dtype, pd.DatetimeTZDtype) or str(s.dt.tz) != "UTC":
        raise ValueError(f"{col} must be tz-aware UTC, got {s.dtype}")


def validate(data: SourceData) -> SourceData:
    df = data.frame
    if data.role == "alerts":
        missing = set(ALERT_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"{data.name}: missing columns {missing}")
        _check_utc(df["start_utc"], "start_utc")
        _check_utc(df["end_utc"], "end_utc")
        if not df["region"].isin(CODES).all():
            raise ValueError(f"{data.name}: unknown region codes")
        if (df["end_utc"] < df["start_utc"]).any():
            raise ValueError(f"{data.name}: alerts ending before they start")
    else:
        missing = set(SIGNAL_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"{data.name}: missing columns {missing}")
        _check_utc(df["published_at_utc"], "published_at_utc")
        if not (df["region"].isna() | df["region"].isin(CODES)).all():
            raise ValueError(f"{data.name}: unknown region codes")
        if not df["kind"].isin(KINDS).all():
            raise ValueError(f"{data.name}: unknown kinds {set(df['kind']) - set(KINDS)}")
    return data
