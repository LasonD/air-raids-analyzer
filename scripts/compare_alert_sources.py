"""One-off check: how far do the official and the volunteer alert histories agree?

Official data is raion-level since Dec 2025 and stops on 2026-09-07, so it is not a source
in the pipeline; this compares both at oblast level (official: any raion/hromada under alert).
Usage: python -m scripts.compare_alert_sources
"""
from __future__ import annotations

import pandas as pd

from airraid.hourly import hourly_matrix
from airraid.paths import RESULTS
from airraid.regions import BY_CODE, BY_CSV_NAME
from airraid.sources import github_csv
from airraid.sources.etryvoga import EtryvogaAlerts

START, END = pd.Timestamp("2026-06-01", tz="UTC"), pd.Timestamp("2026-09-07", tz="UTC")


def main() -> None:
    raw = pd.read_csv(github_csv.fetch("official_data_en.csv"), parse_dates=["started_at", "finished_at"])
    official = pd.DataFrame({"region": raw["oblast"].map(BY_CSV_NAME), "start_utc": raw["started_at"],
                             "end_utc": raw["finished_at"]}).dropna(subset=["region"])
    volunteer = EtryvogaAlerts().load().frame
    hours = pd.date_range(START, END, freq="h", inclusive="left")
    Ho, Hv = hourly_matrix(official, hours, END), hourly_matrix(volunteer, hours, END)
    out = pd.DataFrame({
        "region": [BY_CODE[c].name for c in Ho.columns],
        "official_alert_hours": Ho.mean().round(3).to_numpy(),
        "volunteer_alert_hours": Hv.mean().round(3).to_numpy(),
        "agreement": (Ho == Hv).mean().round(3).to_numpy(),
    }).sort_values("official_alert_hours")
    print(out.to_string(index=False))
    print(f"\noverall hourly agreement {START:%Y-%m-%d}..{END:%Y-%m-%d}: {(Ho.values == Hv.values).mean():.3f}")
    out.to_csv(RESULTS / "alert_source_agreement.csv", index=False)


if __name__ == "__main__":
    main()
