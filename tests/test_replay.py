"""The GUI's replay clock recomputes forecasts stage by stage; it must match the committed backtest
and must not know any outcome after the replay moment."""
import numpy as np
import pandas as pd
import pytest

from airraid import pipeline as P
from airraid.paths import RESULTS

REFERENCE = RESULTS / "predictions.parquet"


@pytest.mark.skipif(not REFERENCE.exists(), reason="needs the committed backtest results")
def test_replay_matches_backtest_and_hides_the_future():
    s = P.Settings()
    now = pd.Timestamp("2026-09-23 05:00", tz="UTC")
    fs = P.features(P.load_sources(), now, s)
    week = P.week_of(s.config(), now)
    long = P.train(fs, s, (), week)

    scored = P.predict(fs, s, None, long, week, now - pd.Timedelta(hours=23))
    ref = pd.read_parquet(REFERENCE).merge(scored, on=["t", "region", "h"], suffixes=("_ref", ""))
    assert len(ref) == len(scored) > 0
    assert np.abs(ref["p_long"] - ref["p_gbm_none"]).max() < 1e-6  # stored as float32
    assert (ref["y"] == ref["y_ref"]).all()

    forecast = P.predict(fs, s, None, long, now, now + P.HOUR)
    assert len(forecast) == 24 * 24
    assert forecast["y"].isna().all()  # no outcome is known at the moment of the forecast
