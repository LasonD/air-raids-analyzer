"""No look-ahead: features at time t must not change when everything after t is removed.

The data is cut the way it was actually known at the cut-off: alerts that started before it
stay (one still running has no known end yet), later alerts and posts disappear.
"""
import numpy as np
import pandas as pd
import pytest

from airraid.config import Config
from airraid.features import Inputs, build, expand, feature_columns, target_hour
from airraid.regions import CODES
from airraid.schema import SourceData

T0 = pd.Timestamp("2026-03-01", tz="UTC")
RNG = np.random.default_rng(42)


def _synthetic_inputs() -> Inputs:
    n = 4000
    start = T0 + pd.to_timedelta(RNG.uniform(0, 90 * 24, n), unit="h")
    alerts = pd.DataFrame({
        "region": RNG.choice(CODES, n),
        "start_utc": start,
        "end_utc": start + pd.to_timedelta(RNG.exponential(1.5, n), unit="h"),
        "end_estimated": False,
    })
    m = 6000
    posts = pd.DataFrame({
        "published_at_utc": T0 + pd.to_timedelta(RNG.uniform(0, 90 * 24, m), unit="h"),
        "region": RNG.choice(list(CODES) + [None], m),
        "kind": RNG.choice(["drone", "missile", "clear", "explosion", "guided_bomb"], m),
        "ref": np.arange(m),
        "edited": False,
    })
    # Some posts name a second region: same post, extra row (as the adapters produce).
    second = posts.sample(1500, random_state=1).assign(region=lambda d: RNG.choice(CODES, len(d)))
    posts = pd.concat([posts, second], ignore_index=True)
    end = T0 + pd.Timedelta(days=90)
    return Inputs(SourceData("alerts", "alerts", alerts, T0, end),
                  [SourceData("chan", "signals", posts, T0, end)])


def _known_at(inputs: Inputs, cut: pd.Timestamp) -> Inputs:
    a = inputs.alerts.frame
    a = a[a["start_utc"] < cut].copy()
    a.loc[a["end_utc"] > cut, "end_utc"] = cut + pd.Timedelta(days=365)  # still running, end unknown
    s = inputs.signals[0]
    p = s.frame[s.frame["published_at_utc"] < cut]
    return Inputs(SourceData("alerts", "alerts", a, inputs.alerts.covered_from, cut),
                  [SourceData(s.name, "signals", p, s.covered_from, cut)])


@pytest.mark.parametrize("cut_hours", [24 * 40 + 0, 24 * 55 + 7, 24 * 70 + 19])
def test_features_do_not_look_ahead(cut_hours):
    cfg = Config()
    inputs = _synthetic_inputs()
    cut = T0 + pd.Timedelta(hours=cut_hours)
    times = pd.date_range(T0 + pd.Timedelta(days=30), cut, freq="h")

    full = expand(build(inputs, times, cfg), cfg.horizons)
    known = expand(build(_known_at(inputs, cut), times, cfg), cfg.horizons)

    cols = feature_columns(full)
    pd.testing.assert_frame_equal(full[cols], known[cols], check_exact=False, rtol=1e-6)
    # Labels after the cut-off are unknown in the truncated data, as they should be.
    assert known.loc[target_hour(known["t"], known["h"]) >= cut, "y"].isna().all()
    # and h=1 is the hour right after issuing
    assert (target_hour(full["t"], full["h"]) - full["t"]).min() == pd.Timedelta(0)


def test_detects_a_planted_leak():
    """Sanity check of the test itself: a feature that peeks at the label must be caught."""
    cfg = Config()
    inputs = _synthetic_inputs()
    cut = T0 + pd.Timedelta(days=50)
    times = pd.date_range(T0 + pd.Timedelta(days=30), cut, freq="h")
    full = expand(build(inputs, times, cfg), cfg.horizons)
    known = expand(build(_known_at(inputs, cut), times, cfg), cfg.horizons)
    full["leak"], known["leak"] = full["y"], known["y"]
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(full[["leak"]], known[["leak"]])
