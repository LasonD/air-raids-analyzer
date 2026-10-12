"""Experiment settings: periods, horizons and which sources are used."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from airraid.sources.github_csv import COMPLETE_UNTIL


@dataclass(frozen=True)
class Config:
    target: str = "etryvoga"                      # alert source that defines the ground truth
    signals: tuple[str, ...] = ("kpszsu", "povitryanatrivogaaa")  # input sources switched on
    data_end: pd.Timestamp = COMPLETE_UNTIL       # alert data is complete before this
    test_days: int = 28                           # test = last 28 days of labelled data
    val_days: int = 28                            # validation = the 28 days before the test
    train_days: int = 182                         # rolling training window
    retrain_days: int = 7                         # retrain weekly inside the test period
    horizons: tuple[int, ...] = tuple(range(1, 25))
    max_alert_hours: float = 12.0                 # longer alerts are treated as a missed all-clear
    train_horizons_per_row: int = 3               # horizons sampled per training issue time (memory)
    # Telegram shows the publish time but the latest text, and the edit time is unknown: edited posts
    # may carry later information (route summaries are updated in place), so they are dropped.
    exclude_edited: bool = True
    seed: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def test_start(self) -> pd.Timestamp:
        return self.data_end - pd.Timedelta(days=self.test_days)

    @property
    def val_start(self) -> pd.Timestamp:
        return self.test_start - pd.Timedelta(days=self.val_days)

    @property
    def feature_start(self) -> pd.Timestamp:
        """First issue time features are built for (training window of the first validation week)."""
        return self.val_start - pd.Timedelta(days=self.train_days)
