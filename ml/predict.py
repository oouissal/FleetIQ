"""Model serving helpers: load MLflow-registered models and predict.

Used by the FastAPI layer (POST /api/predict/eta, POST /api/predict/anomaly).
Both predictors are lazy singletons: the model is loaded on first use and
the load event is logged (observability).

ETA interval methodology: prediction ± 1.96 * std(validation residuals).
This is an approximate, homoscedastic interval — NOT a calibrated
conformal interval. Stated in the API response as "method": "residual".
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import joblib
import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient

from ml.features import ANOMALY_FEATURES, ETA_FEATURES

log = logging.getLogger("ml.predict")

ETA_MODEL_NAME = "eta_prediction"
ANOMALY_MODEL_NAME = "anomaly_detection"
INTERVAL_Z = 1.96
# MLflow 3.x put the local file store in maintenance mode; use a sqlite
# backend by default unless the user explicitly opted in to the file store.
LOCAL_SQLITE_URI = "sqlite:///mlruns/mlflow.db"


def resolve_tracking_uri(uri: str | None) -> str:
    """Pick a working local tracking URI when none is configured."""
    if uri:
        if uri.startswith("file://"):
            os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        return uri
    if os.environ.get("MLFLOW_ALLOW_FILE_STORE") == "true":
        return ""  # classic ./mlruns file store, explicitly allowed
    return LOCAL_SQLITE_URI
DEFAULT_TYPICAL_SPEED_KMH = 55.0


# ---------------------------------------------------------------------------
# MLflow helpers
# ---------------------------------------------------------------------------
def _client(tracking_uri: str) -> MlflowClient:
    return MlflowClient(tracking_uri=resolve_tracking_uri(tracking_uri) or None)


def latest_model_version(tracking_uri: str, name: str) -> dict[str, Any]:
    """Metadata of the latest registered version of a model."""
    try:
        mv = _client(tracking_uri).get_latest_versions(name)
        if not mv:
            raise LookupError(f"No registered model named {name!r}")
        prod = [v for v in mv if v.current_stage == "Production"]
        chosen = prod[0] if prod else max(mv, key=lambda v: int(v.version))
        return {
            "name": name,
            "version": chosen.version,
            "stage": chosen.current_stage,
            "run_id": chosen.run_id,
            "creation_timestamp_ms": chosen.creation_timestamp,
        }
    except Exception as exc:  # surface a clean error to the API (re-raised)
        log.error("Could not resolve model %s: %s", name, exc)
        raise


def load_mlflow_sklearn(tracking_uri: str, name: str, version: Optional[str] = None):
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    uri = f"models:/{name}/{version or 'latest'}"
    return mlflow.sklearn.load_model(uri)


# ---------------------------------------------------------------------------
# ETA prediction
# ---------------------------------------------------------------------------
def build_eta_feature_vector(payload: dict[str, Any]) -> pd.DataFrame:
    """Map an API payload to the ETA feature matrix (one row).

    Accepts: distance_km, vehicle_type, dispatch_time (ISO), route_id,
    congestion_factor, historical_route_duration_min, weather, parcels,
    stop_index. Unknown values fall back to neutral defaults (documented).
    """
    now = datetime.now(timezone.utc)
    dispatch = payload.get("dispatch_time") or now.isoformat()
    dt = pd.to_datetime(dispatch)
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")

    distance = float(payload.get("distance_km") or 0.0)
    hist = payload.get("historical_route_duration_min")
    typical_speed = (distance / float(hist) * 60.0
                     if hist and float(hist) > 0 else DEFAULT_TYPICAL_SPEED_KMH)

    vtype = str(payload.get("vehicle_type") or "BOX_TRUCK").upper()
    weather = str(payload.get("weather") or "clear").lower()

    row: dict[str, Any] = {f: 0.0 for f in ETA_FEATURES}
    row["planned_distance_km"] = distance
    row["typical_speed_kmh"] = typical_speed
    row["congestion_factor"] = float(payload.get("congestion_factor") or 1.0)
    row["hour"] = dt.hour + dt.minute / 60.0
    row["day_of_week"] = dt.dayofweek
    row["parcels"] = float(payload.get("parcels") or 10)
    row["stop_index"] = float(payload.get("stop_index") or 0)
    row["historical_route_duration_min"] = float(hist or 0.0)
    row["weather_rain"] = 1.0 if weather == "rain" else 0.0
    row["weather_storm"] = 1.0 if weather == "storm" else 0.0
    for col in ("vehicle_type_VAN", "vehicle_type_BOX_TRUCK",
                "vehicle_type_SEMI_TRAILER", "vehicle_type_REFRIGERATED"):
        row[col] = 1.0 if col.endswith(vtype) else 0.0
    return pd.DataFrame([row], columns=ETA_FEATURES)


class EtaPredictor:
    """Lazy singleton around the registered ETA model."""

    _instance: Optional["EtaPredictor"] = None

    def __init__(self, tracking_uri: str, interval_half: float = 25.0) -> None:
        self.tracking_uri = tracking_uri
        self.interval_half = interval_half
        self._model = None
        self._meta: dict[str, Any] = {}

    @classmethod
    def get(cls, tracking_uri: str, interval_half: float = 25.0) -> "EtaPredictor":
        if cls._instance is None or cls._instance.tracking_uri != tracking_uri:
            cls._instance = cls(tracking_uri, interval_half)
        return cls._instance

    @property
    def model(self):
        if self._model is None:
            log.info("Loading ETA model from MLflow (%s)", self.tracking_uri)
            self._meta = latest_model_version(self.tracking_uri, ETA_MODEL_NAME)
            self._model = load_mlflow_sklearn(self.tracking_uri, ETA_MODEL_NAME)
            log.info("ETA model loaded: version=%s run=%s",
                     self._meta["version"], self._meta["run_id"])
        return self._model

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        X = build_eta_feature_vector(payload)
        pred = float(self.model.predict(X)[0])
        return {
            "predicted_eta_minutes": round(max(0.0, pred), 2),
            "interval": {
                "method": "residual",
                "description": "prediction ± 1.96 * std(validation residuals); "
                               "approximate, not calibrated",
                "lower_minutes": round(max(0.0, pred - self.interval_half), 2),
                "upper_minutes": round(pred + self.interval_half, 2),
            },
            "model_version": self._meta.get("version"),
            "model_run_id": self._meta.get("run_id"),
            "prediction_timestamp": datetime.now(timezone.utc).isoformat(),
            "features_used": X.iloc[0].to_dict(),
        }


# ---------------------------------------------------------------------------
# Anomaly prediction
# ---------------------------------------------------------------------------
class AnomalyPredictor:
    """Lazy singleton around the registered Isolation Forest + scaler."""

    _instance: Optional["AnomalyPredictor"] = None

    def __init__(self, tracking_uri: str, scaler_path: Optional[Path] = None) -> None:
        self.tracking_uri = tracking_uri
        self.scaler_path = scaler_path
        self._model = None
        self._scaler = None
        self._meta: dict[str, Any] = {}

    @classmethod
    def get(cls, tracking_uri: str, scaler_path: Optional[Path] = None) -> "AnomalyPredictor":
        if cls._instance is None or cls._instance.tracking_uri != tracking_uri:
            cls._instance = cls(tracking_uri, scaler_path)
        return cls._instance

    @property
    def model(self):
        if self._model is None:
            log.info("Loading anomaly model from MLflow (%s)", self.tracking_uri)
            self._meta = latest_model_version(self.tracking_uri, ANOMALY_MODEL_NAME)
            self._model = load_mlflow_sklearn(self.tracking_uri, ANOMALY_MODEL_NAME)
            if self.scaler_path and self.scaler_path.exists():
                self._scaler = joblib.load(self.scaler_path)
            log.info("Anomaly model loaded: version=%s run=%s",
                     self._meta["version"], self._meta["run_id"])
        return self._model

    def predict(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Score one or more telemetry rows; returns per-row results."""
        X = pd.DataFrame(rows, columns=ANOMALY_FEATURES).astype(float)
        if self._scaler is not None:
            Xs = self._scaler.transform(X)
        else:
            Xs = X.values  # model was trained on standardized data
        scores = self.model.score_samples(Xs)
        flags = self.model.predict(Xs)
        out = []
        for i in range(len(rows)):
            out.append({
                "anomaly_score": round(float(scores[i]), 4),
                "anomaly_flag": bool(flags[i] == -1),
                "description": ("Unusual telemetry pattern detected."
                                if flags[i] == -1 else "No unusual pattern."),
            })
        return out
