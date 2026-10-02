"""ETA model training: Baseline -> Random Forest -> XGBoost, tracked in MLflow.

Selection methodology (explicit, no arbitrary "best"):
    * All models are evaluated on the same time-ordered validation split.
    * The model with the lowest RMSE on the VALIDATION set is registered
      as the production ETA model ("eta_prediction").
    * Final metrics are reported on the untouched FUTURE test set.
    * The baseline (global median) defines the minimum bar: a candidate
      model must beat it on validation RMSE to be considered.

Usage:
    python -m ml.train_eta --raw data/raw --experiment supply-chain-intelligence
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import mlflow
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from xgboost import XGBRegressor

from ml.evaluate import baseline_metrics, regression_metrics, residual_interval
from ml.features import ETA_FEATURES, TARGET, build_eta_dataset, temporal_split
from ml.predict import resolve_tracking_uri

log = logging.getLogger("ml.train_eta")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s - %(message)s")

EXPERIMENT = "supply-chain-intelligence"
MODEL_NAME = "eta_prediction"


def _prep(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    X = df[ETA_FEATURES].copy()
    y = df[TARGET].astype(float)
    return X, y


def _fit_and_measure(name: str, model, X_train, y_train, X_val, y_val,
                     params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    t0 = time.time()
    model.fit(X_train, y_train)
    train_time_s = time.time() - t0
    val_metrics = regression_metrics(y_val, model.predict(X_val))
    with mlflow.start_run(run_name=name, nested=True):
        mlflow.set_tag("model_type", name)
        if params:
            mlflow.log_params(params)
        mlflow.log_metrics({f"val_{k}": v for k, v in val_metrics.items()})
        mlflow.log_metric("training_duration_s", train_time_s)
        mlflow.sklearn.log_model(
            model, artifact_path="model",
            input_example=X_train.iloc[:5],
            registered_model_name=MODEL_NAME,
            skops_trusted_types=[
                "sklearn.tree._tree.Tree",
                "xgboost.core.Booster",
                "xgboost.sklearn.XGBRegressor",
            ])
    log.info("%s: train=%.1fs val_mae=%.2f val_rmse=%.2f val_r2=%.3f",
             name, train_time_s, val_metrics["mae"], val_metrics["rmse"],
             val_metrics["r2"])
    return {**val_metrics, "train_time_s": train_time_s, "model": model}


def train(raw_dir: Path, tracking_uri: Optional[str] = None,
          results_file: Optional[Path] = None) -> dict[str, Any]:
    mlflow.set_tracking_uri(resolve_tracking_uri(tracking_uri))
    mlflow.set_experiment(EXPERIMENT)

    df = build_eta_dataset(raw_dir)
    train_df, val_df, test_df = temporal_split(df)
    X_train, y_train = _prep(train_df)
    X_val, y_val = _prep(val_df)
    X_test, y_test = _prep(test_df)
    log.info("Split sizes: train=%s val=%s test=%s (time-ordered)",
             len(X_train), len(X_val), len(X_test))

    results: dict[str, Any] = {
        "dataset_rows": int(len(df)),
        "train_rows": int(len(X_train)),
        "val_rows": int(len(X_val)),
        "test_rows": int(len(X_test)),
        "features": ETA_FEATURES,
        "target": TARGET,
        "split": "time-ordered 70/15/15; test = future observations",
    }

    with mlflow.start_run(run_name="eta-baseline") as run:
        base = baseline_metrics(y_train, y_val, y_test, strategy="median")
        mlflow.log_metrics({f"test_{k}": v for k, v in base.items()})
        mlflow.set_tag("model_type", "baseline_median")
        results["baseline"] = {"metrics_test": base, "run_id": run.info.run_id}
        log.info("Baseline(median) test: mae=%.2f rmse=%.2f r2=%.3f",
                 base["mae"], base["rmse"], base["r2"])

    candidates = {}
    rf_params = {"n_estimators": 300, "max_depth": 18, "min_samples_leaf": 3,
                 "n_jobs": -1, "random_state": 42}
    xgb_params = {"n_estimators": 400, "max_depth": 6, "learning_rate": 0.05,
                  "subsample": 0.9, "colsample_bytree": 0.9,
                  "random_state": 42, "n_jobs": -1,
                  "eval_metric": "rmse"}

    candidates["random_forest"] = _fit_and_measure(
        "random_forest", RandomForestRegressor(**rf_params),
        X_train, y_train, X_val, y_val, rf_params)
    candidates["xgboost"] = _fit_and_measure(
        "xgboost",
        XGBRegressor(**xgb_params, enable_categorical=False),
        X_train, y_train, X_val, y_val, xgb_params)

    # Selection: lowest validation RMSE, must beat the baseline.
    best_name = min(candidates, key=lambda k: candidates[k]["rmse"])
    best = candidates[best_name]
    baseline_ok = best["rmse"] < results["baseline"]["metrics_test"]["rmse"]
    results["selection"] = {
        "method": "lowest validation RMSE among candidates that beat the "
                  "median baseline on validation",
        "selected_model": best_name if baseline_ok else "none",
        "baseline_beat": baseline_ok,
    }

    if baseline_ok:
        with mlflow.start_run(run_name=f"eta-final-{best_name}") as run:
            t0 = time.time()
            best["model"].fit(pd.concat([X_train, X_val]),
                              pd.concat([y_train, y_val]))
            test_pred = best["model"].predict(X_test)
            test_metrics = regression_metrics(y_test, test_pred)
            interval_half = residual_interval(y_val, best["model"].predict(X_val))
            mlflow.log_metrics({f"test_{k}": v for k, v in test_metrics.items()})
            mlflow.log_metric("refit_duration_s", time.time() - t0)
            mlflow.set_tag("model_type", best_name)
            mlflow.sklearn.log_model(
                best["model"], artifact_path="model",
                input_example=X_train.iloc[:5],
                registered_model_name=MODEL_NAME,
                skops_trusted_types=[
                    "sklearn.tree._tree.Tree",
                    "xgboost.core.Booster",
                    "xgboost.sklearn.XGBRegressor",
                ])
            results["final"] = {
                "model": best_name,
                "metrics_test": test_metrics,
                "interval_half_width_min": interval_half,
                "run_id": run.info.run_id,
            }
            log.info("FINAL %s: test_mae=%.2f test_rmse=%.2f test_r2=%.3f "
                     "interval±%.1fmin", best_name, test_metrics["mae"],
                     test_metrics["rmse"], test_metrics["r2"], interval_half)
    else:
        results["final"] = {"model": "baseline", "note":
                            "No candidate beat the baseline; nothing registered."}

    if results_file:
        results_file.parent.mkdir(parents=True, exist_ok=True)
        results_file.write_text(json.dumps(results, indent=2))
        log.info("Results written to %s", results_file)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", default="data/raw", help="directory with raw parquet files")
    p.add_argument("--tracking-uri", default=None,
                   help="MLflow tracking URI (default: local ./mlruns)")
    p.add_argument("--results", default="ml/mlruns_meta/eta_results.json",
                   help="path for the JSON summary")
    args = p.parse_args(argv)
    train(Path(args.raw), args.tracking_uri, Path(args.results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

