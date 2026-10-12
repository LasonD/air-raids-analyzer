"""Volunteer alert history (eTryvoga channel, via the Vadimkin dataset): oblast-level intervals."""
from __future__ import annotations

import pandas as pd

from airraid.regions import BY_CSV_NAME
from airraid.schema import SourceData, validate
from airraid.sources import github_csv

FILE = "volunteer_data_en.csv"


class EtryvogaAlerts:
    name = "etryvoga"
    role = "alerts"

    def fetch(self) -> None:
        github_csv.fetch(FILE)

    def load(self) -> SourceData:
        raw = pd.read_csv(github_csv.fetch(FILE), parse_dates=["started_at", "finished_at"])
        df = pd.DataFrame({
            "region": raw["region"].map(BY_CSV_NAME),  # excluded regions (Luhansk) map to NaN
            "start_utc": raw["started_at"],
            "end_utc": raw["finished_at"],
            "end_estimated": raw["naive"].astype(bool),
        }).dropna(subset=["region"])
        return validate(SourceData(self.name, "alerts", df.reset_index(drop=True),
                                   df["start_utc"].min().floor("D"), github_csv.COMPLETE_UNTIL))
