"""95 % ranges for skill scores, by resampling whole days (hours within a day are not independent)."""
from __future__ import annotations

import numpy as np
import pandas as pd

# (name, model, comparison): skill of `model` vs climatology, minus the same for `comparison` if given.
METRICS = [
    ("main_vs_climatology", "p_main", None),
    ("alertmap_minus_none", "p_gbm_alertmap", "p_gbm_none"),
    ("kpszsu_minus_none", "p_gbm_kpszsu", "p_gbm_none"),
]
GROUPS = {"1": (1, 1), "2-3": (2, 3), "4-24": (4, 24), "1-24": (1, 24)}


def _daily_errors(pred: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, list[str]]:
    """Sum of squared errors per (day, horizon) for each column: array [column, day, horizon]."""
    day = pred["t"].dt.tz_convert("Europe/Kyiv").dt.date
    err = pd.DataFrame({c: (pred[c] - pred["y"]) ** 2 for c in cols}).assign(day=day.to_numpy(), h=pred["h"].to_numpy())
    g = err.groupby(["day", "h"])[cols].sum().unstack("h", fill_value=0.0)
    return np.stack([g[c].to_numpy() for c in cols]), list(g.index)


def bootstrap(pred: pd.DataFrame, reps: int = 1000, seed: int = 0) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(seed)
    for period in ("validation", "test"):
        for subset in ("all", "quiet"):
            sub = pred[pred["period"] == period]
            if subset == "quiet":
                sub = sub[sub["active_now"] == 0]
            cols = sorted({"p_climatology"} | {c for _, a, b in METRICS for c in (a, b) if c})
            E, days = _daily_errors(sub, cols)
            idx = rng.integers(0, len(days), size=(reps, len(days)))
            boot = E[:, idx, :].sum(axis=2)          # [column, rep, horizon]
            full = E.sum(axis=1)                     # [column, horizon]
            ci = {c: i for i, c in enumerate(cols)}
            labels = [str(h) for h in range(1, E.shape[2] + 1)] + list(GROUPS)
            for name, a, b in METRICS:
                def skill(S, col):
                    return 1 - S[..., ci[col]] / S[..., ci["p_climatology"]]
                for label in labels:
                    lo_h, hi_h = GROUPS[label] if label in GROUPS else (int(label), int(label))
                    sl = slice(lo_h - 1, hi_h)
                    point_s = full[:, sl].sum(axis=1)                   # [column]
                    boot_s = boot[:, :, sl].sum(axis=2).T               # [rep, column]
                    point = skill(point_s, a) - (skill(point_s, b) if b else 0)
                    dist = skill(boot_s, a) - (skill(boot_s, b) if b else 0)
                    lo, hi = np.percentile(dist, [2.5, 97.5])
                    rows.append({"metric": name, "period": period, "subset": subset, "h": label,
                                 "point": float(point), "lo": float(lo), "hi": float(hi)})
    return pd.DataFrame(rows)
