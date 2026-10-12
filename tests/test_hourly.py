import numpy as np
import pandas as pd

from airraid.hourly import alert_state, cap_durations, hourly_matrix

T = lambda s: pd.Timestamp(f"2026-05-01 {s}", tz="UTC")


def _alerts(*spans, region="UA-30"):
    return pd.DataFrame({"region": region, "start_utc": [T(a) for a, _ in spans], "end_utc": [T(b) for _, b in spans],
                         "end_estimated": False})


def test_hour_is_active_if_any_alert_overlaps_it():
    hours = pd.date_range(T("08:00"), T("15:00"), freq="h", inclusive="left")
    H = hourly_matrix(_alerts(("10:30", "11:10"), ("13:00", "14:00")), hours, covered_to=T("14:00"))["UA-30"]
    assert H[T("09:00")] == 0
    assert H[T("10:00")] == 1 and H[T("11:00")] == 1   # 10:30-11:10 touches both hours
    assert H[T("12:00")] == 0
    assert H[T("13:00")] == 1                          # ends exactly at 14:00: hour 14 not touched
    assert np.isnan(H[T("14:00")])                     # past the end of the data: unknown


def test_alert_state_uses_only_what_has_started():
    times = pd.DatetimeIndex([T("10:00"), T("10:45"), T("12:00")])
    s = alert_state(_alerts(("10:30", "11:10")), times)
    assert list(s["active_now"]["UA-30"]) == [0, 1, 0]
    assert s["elapsed_h"]["UA-30"].iloc[1] == 0.25
    assert s["since_end_h"]["UA-30"].iloc[2] == np.float32(50 / 60)


def test_overlong_alerts_are_capped():
    capped = cap_durations(_alerts(("00:00", "23:00")), max_hours=12)
    assert capped["end_utc"].iat[0] == T("12:00")
