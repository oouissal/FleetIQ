"""Shared model evaluation utilities (regression)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def regression_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    """MAE / RMSE / R² — the only metrics reported for ETA models."""
    y = np.asarray(y_true, dtype=float)
    return {
        "mae": float(mean_absolute_error(y, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y, y_pred))),
        "r2": float(r2_score(y, y_pred)),
    }


def baseline_metrics(y_train: pd.Series, y_val: pd.Series,
                     y_test: pd.Series, strategy: str = "median") -> dict[str, float]:
    """Naive baseline (no features): median of training durations."""
    if strategy == "median":
        pred_val = float(np.median(y_train))
    elif strategy == "mean":
        pred_val = float(np.mean(y_train))
    else:
        raise ValueError(f"Unknown baseline strategy: {strategy}")
    return regression_metrics(y_test, np.full(len(y_test), pred_val))


def residual_interval(y_true: pd.Series, y_pred: np.ndarray,
                      z: float = 1.96) -> float:
    """Empirical (residual-based) half-width for a ~95% prediction interval.

    Methodology (documented in docs/ml-methodology.md): the interval is
    ``prediction ± z * std(residuals)`` computed on the validation set.
    This is an approximation — it assumes homoscedastic residuals — and is
    NOT a calibrated conformal interval.
    """
    residuals = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(z * float(np.std(residuals)))
