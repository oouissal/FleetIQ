"""Unsupervised anomaly detection: Isolation Forest on vehicle telemetry.

Methodology (documented in docs/ml-methodology.md):
    * Inputs: per-event telemetry features (speed, acceleration, fuel rate,
      engine load, engine temp, ambient temp, idle time).
    * StandardScaler + IsolationForest with contamination=0.02 (expected
      share of unusual events, a modelling choice, not ground truth).
    * Outputs per event: anomaly_score (-0.5..1), anomaly_flag (top 2%),
      and anomaly_type — a DESCRIPTION OF THE PATTERN, not a root cause.
      anomaly_type is derived from robust z-scores of the flagged event:
      the strongest deviating feature(s) name the pattern, e.g.
      "high_engine_temp_c". This is NOT a claim that the engine overheated.

Limitations (stated honestly):
    * Unsupervised: no labels are used; "anomalous" = unusual relative to
      the fleet-wide distribution. Unusual does not imply faulty.
    * The synthetic generator injects anomalies with known ground truth;
      that ground truth is used ONLY in the evaluation report, never in
      training. Real deployments would not have such labels.

Usage:
    python -m ml.train_anomaly --raw data/raw --out data_lake/gold/anomalies
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import joblib
import mlflow
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from ml.features import ANOMALY_FEATURES, build_anomaly_features

log = logging.getLogger("ml.train_anomaly")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s - %(message)s")

EXPERIMENT = "supply-chain-intelligence"
MODEL_NAME = "anomaly_detection"
CONTAMINATION = 0.02
RANDOM_STATE = 42


def pattern_for_event(row: pd.Series, medians: pd.Series,
                      scales: pd.Series) -> list[str]:
    """Describe the pattern of a flagged event from robust z-scores.

    Returns the top deviating features as "<direction>_<feature>" names.
    Direction language: "high_*" / "low_*" — a description of the measured
    values, NOT of a physical fault.
    """
    deviations = []
    for col in ANOMALY_FEATURES:
        if scales[col] <= 0:
            continue
        z = (row[col] - medians[col]) / scales[col]
        if z > 3.0:
            deviations.append((abs(z), f"high_{col}"))
        elif z < -3.0:
            deviations.append((abs(z), f"low_{col}"))
    deviations.sort(reverse=True)
    return [name for _, name in deviations[:3]]


def train(raw_dir: Path, out_dir: Path, tracking_uri: Optional[str] = None,
          contamination: float = CONTAMINATION) -> dict[str, Any]:
    mlflow.set_tracking_uri(tracking_uri or "")
    mlflow.set_experiment(EXPERIMENT)

    tele = build_anomaly_features(raw_dir)
    X = tele[ANOMALY_FEATURES].astype(float)

    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

    t0 = time.time()
    model = IsolationForest(
        n_estimators=200, max_samples=256, contamination=contamination,
        random_state=RANDOM_STATE, n_jobs=-1)
    model.fit(Xs)
    train_time_s = time.time() - t0

    scores = model.score_samples(Xs)
    flags = model.predict(Xs)  # +1 inlier, -1 outlier
    tele = tele.copy()
    tele["anomaly_score"] = scores
    tele["anomaly_flag"] = (flags == -1)
    tele["anomaly_raw_score"] = -scores  # higher = more anomalous (UI friendly)

    medians = X.median()
    scales = (X - medians).abs().median() * 1.4826  # robust MAD-based scale
    tele["anomaly_type"] = tele.apply(
        lambda row: pattern_for_event(row, medians, scales)
        if row["anomaly_flag"] else [], axis=1)

    n_flagged = int(tele["anomaly_flag"].sum())
    results = {
        "method": "IsolationForest (unsupervised)",
        "contamination": contamination,
        "n_events": int(len(tele)),
        "n_flagged": n_flagged,
        "flagged_share": round(n_flagged / max(1, len(tele)), 4),
        "features": ANOMALY_FEATURES,
        "train_duration_s": round(train_time_s, 2),
        "note": "anomaly_flag = IsolationForest prediction, NOT a fault label. "
                "anomaly_type describes the deviating measurement pattern.",
    }

    with mlflow.start_run(run_name="anomaly-isolation-forest") as run:
        mlflow.log_params({
            "n_estimators": 200, "max_samples": 256,
            "contamination": contamination, "random_state": RANDOM_STATE,
        })
        mlflow.log_metrics({"n_events": len(tele), "n_flagged": n_flagged,
                            "flagged_share": results["flagged_share"],
                            "training_duration_s": train_time_s})
        mlflow.set_tag("model_type", "isolation_forest")
        mlflow.sklearn.log_model(model, artifact_path="model",
                                 registered_model_name=MODEL_NAME)
        joblib.dump(scaler, out_dir / "anomaly_scaler.joblib")
        mlflow.log_artifact(str(out_dir / "anomaly_scaler.joblib"))
        results["run_id"] = run.info.run_id

    out_dir.mkdir(parents=True, exist_ok=True)
    tele[["event_id", "vehicle_id", "timestamp"] + ANOMALY_FEATURES
         + ["anomaly_score", "anomaly_raw_score", "anomaly_flag",
            "anomaly_type"]].to_parquet(out_dir / "anomalies.parquet", index=False)
    (out_dir / "anomaly_metadata.json").write_text(json.dumps(results, indent=2))

    log.info("Anomaly model trained: %s/%s events flagged (%.2f%%) in %.1fs",
             n_flagged, len(tele), 100 * results["flagged_share"], train_time_s)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", default="data/raw", help="directory with raw parquet files")
    p.add_argument("--out", default="data_lake/gold/anomalies",
                   help="output directory for anomalies.parquet + scaler")
    p.add_argument("--tracking-uri", default=None, help="MLflow tracking URI")
    p.add_argument("--contamination", type=float, default=CONTAMINATION)
    args = p.parse_args(argv)
    train(Path(args.raw), Path(args.out), args.tracking_uri, args.contamination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

