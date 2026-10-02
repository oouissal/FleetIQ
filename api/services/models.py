"""Model service: metadata + predictors used by the API.

Metadata comes from files written by the training scripts (actual measured
metrics) and from the MLflow registry. When models are absent the service
returns honest 503-style errors; it never fabricates metrics.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from api.config import ApiConfig

log = logging.getLogger("api.models")


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 - corrupted meta must not kill API
        log.warning("Could not read %s: %s", path, exc)
    return None


def eta_model_info(cfg: ApiConfig) -> Optional[dict[str, Any]]:
    """Actual metrics from the training run + registry metadata."""
    results = _read_json(cfg.results_meta_path / "eta_results.json")
    if not results or "final" not in results:
        return None
    final = results["final"]
    info = {
        "model_name": "eta_prediction",
        "model_type": final.get("model", "unknown"),
        "metrics": final.get("metrics_test"),
        "interval_half_width_min": final.get("interval_half_width_min"),
        "run_id": final.get("run_id"),
        "dataset_rows": results.get("dataset_rows"),
        "split": results.get("split"),
        "selection": results.get("selection", {}).get("method"),
        "baseline_metrics": results.get("baseline", {}).get("metrics_test"),
        "note": "Metrics measured on the future test set of synthetic data.",
    }
    try:
        from ml.predict import latest_model_version

        mv = latest_model_version(cfg.mlflow_tracking_uri, "eta_prediction")
        info["registry_version"] = mv["version"]
        info["training_timestamp"] = mv["creation_timestamp_ms"]
    except Exception as exc:  # noqa: BLE001 - registry is optional metadata
        log.warning("MLflow registry unavailable for eta model: %s", exc)
    return info


def anomaly_model_info(cfg: ApiConfig) -> Optional[dict[str, Any]]:
    meta = _read_json(cfg.anomaly_meta_path / "anomaly_metadata.json")
    if not meta:
        return None
    info = {
        "model_name": "anomaly_detection",
        "method": meta.get("method"),
        "contamination": meta.get("contamination"),
        "n_events": meta.get("n_events"),
        "n_flagged": meta.get("n_flagged"),
        "flagged_share": meta.get("flagged_share"),
        "features": meta.get("features"),
        "run_id": meta.get("run_id"),
        "limitations": [
            "Unsupervised: 'anomalous' means unusual relative to the fleet "
            "distribution, not necessarily faulty.",
            "anomaly_type describes the deviating measurement pattern, not "
            "a root cause.",
            "Trained on synthetic data only.",
        ],
    }
    return info
