"""Baselines and the gradient boosting model. All take the expanded feature frame."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from airraid.features import feature_columns

# Simple baselines need no training.
BASELINES = {
    "climatology": lambda X: X["clim_28d"].to_numpy(),      # this region, this hour of day, last 28 days
    "persistence": lambda X: X["active_now"].to_numpy(),    # "as it is now"
}
LOGIT_FEATURES = ["active_now", "elapsed_h", "rate_3h", "rate_24h", "clim_28d", "same_hour_prev", "h"]


def signal_columns(columns: list[str], sources: tuple[str, ...]) -> list[str]:
    """Drop the Telegram feature columns of sources that are switched off."""
    return [c for c in columns if not c.startswith("sig__") or c.split("__")[1] in sources]


class Logistic:
    """Alert history only, linear: a stronger baseline than climatology."""

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "Logistic":
        Z = X[LOGIT_FEATURES].fillna(0).assign(act_h=X["active_now"] * X["h"])
        self.model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)).fit(Z, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        Z = X[LOGIT_FEATURES].fillna(0).assign(act_h=X["active_now"] * X["h"])
        return self.model.predict_proba(Z)[:, 1]


class Boosting:
    def __init__(self, sources: tuple[str, ...], seed: int = 0):
        self.sources = sources
        self.seed = seed

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "Boosting":
        self.columns = signal_columns(feature_columns(X), self.sources)
        self.model = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.08, max_leaf_nodes=63, min_samples_leaf=200,
            l2_regularization=1.0, categorical_features=["region"], early_stopping=False,
            random_state=self.seed,
        ).fit(X[self.columns], y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X[self.columns])[:, 1]
