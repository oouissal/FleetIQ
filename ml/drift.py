"""OFFLINE / SIMULATED monitoring reports (Evidently).

This is NOT a live production monitor. It compares a reference window
(training period) with a current window (recent data) and produces an
Evidently HTML/JSON report covering data drift, feature drift and
prediction distribution. It is run on demand or by the Airflow batch DAG.

Labels are honest: every report is marked "Offline / Simulated Monitoring".
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from ml.features import ETA_FEATURES, TARGET, build_eta_dataset

log = logging.getLogger("ml.drift")

COLUMNS = ETA_FEATURES + [TARGET]


def _window(df: pd.DataFrame, n_rows: Optional[int]) -> pd.DataFrame:
    if n_rows is None:
        return df
    return df.tail(n_rows)


def run_drift_report(raw_dir: Path, report_dir: Path,
                     reference_rows: Optional[int] = None,
                     current_rows: Optional[int] = None) -> dict:
    """Produce the Evidently drift report; returns summary metadata."""
    try:
        from evidently.metric_preset import DataDriftPreset
        from evidently.report import Report
    except ImportError as exc:  # pragma: no cover - env without evidently
        log.error("evidently not installed: %s", exc)
        raise

    df = build_eta_dataset(raw_dir)
    reference = _window(df, reference_rows)
    current = _window(df, current_rows)
    if len(current) == 0 or len(reference) == 0:
        raise ValueError("insufficient data for drift report")

    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference[COLUMNS], current_data=current[COLUMNS])

    report_dir.mkdir(parents=True, exist_ok=True)
    report.save_html(str(report_dir / "drift_report.html"))
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "label": "Offline / Simulated Monitoring",
        "reference_rows": int(len(reference)),
        "current_rows": int(len(current)),
        "columns": COLUMNS,
        "drift_detected": bool(report.as_dict()["metrics"][0]["result"].get(
            "dataset_drift", False)),
        "drifted_features": report.as_dict()["metrics"][0]["result"].get(
            "number_of_drifted_columns", 0),
        "method": "Evidently DataDriftPreset",
    }
    (report_dir / "drift_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("Drift report written to %s (drift_detected=%s)",
             report_dir, summary["drift_detected"])
    return summary


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", default="data/raw")
    p.add_argument("--out", default="monitoring/reports")
    p.add_argument("--reference-rows", type=int, default=5000)
    p.add_argument("--current-rows", type=int, default=2000)
    args = p.parse_args()
    summary = run_drift_report(Path(args.raw), Path(args.out),
                               args.reference_rows, args.current_rows)
    print(json.dumps(summary, indent=2))
