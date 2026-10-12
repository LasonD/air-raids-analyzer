"""Scores for probability forecasts: Brier score, log loss, ROC AUC and calibration."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from airraid.regions import BY_CODE, CODES


def model_columns(pred: pd.DataFrame) -> list[str]:
    return [c for c in pred.columns if c.startswith("p_")]


def scores(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return {
        "brier": brier_score_loss(y, p),
        "log_loss": log_loss(y, p, labels=[0, 1]),
        "auc": roc_auc_score(y, p) if 0 < y.mean() < 1 else np.nan,
    }


def summary(pred: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """One row per model (and group); brier_skill = 1 - brier / brier of climatology."""
    rows = []
    groups = pred.groupby(by) if by else [((), pred)]
    for key, g in groups:
        key = key if isinstance(key, tuple) else (key,)
        ref = scores(g["y"].to_numpy(), g["p_climatology"].to_numpy())["brier"]
        for col in model_columns(g):
            s = scores(g["y"].to_numpy(), g[col].to_numpy())
            rows.append({**dict(zip(by or [], key)), "model": col[2:], **s, "brier_skill": 1 - s["brier"] / ref, "n": len(g)})
    return pd.DataFrame(rows)


def calibration(pred: pd.DataFrame, col: str, bins: int = 10) -> pd.DataFrame:
    """Mean predicted probability vs observed alert frequency per probability bin."""
    b = np.minimum((pred[col] * bins).astype(int), bins - 1)
    return pred.groupby(b).agg(predicted=(col, "mean"), observed=("y", "mean"), n=("y", "size")).reset_index(drop=True)


def region_names(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(region_name=frame["region"].map(lambda i: BY_CODE[CODES[i]].name))
