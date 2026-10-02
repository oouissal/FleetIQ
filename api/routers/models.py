"""Model info + prediction endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.config import ApiConfig, get_config
from api.schemas import AnomalyPrediction, AnomalyRequest, EtaRequest
from api.services.models import anomaly_model_info, eta_model_info

log = logging.getLogger("api.models")

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/model/info", summary="ETA + anomaly model metadata and metrics")
def model_info(cfg: ApiConfig = Depends(get_config)) -> dict:
    eta = eta_model_info(cfg)
    anomaly = anomaly_model_info(cfg)
    return {
        "eta_model": eta,
        "anomaly_model": anomaly,
        "available": bool(eta and anomaly),
        "note": "Metrics are actual values measured on synthetic data; "
                "see docs/ml-methodology.md for the evaluation protocol.",
    }


@router.post("/predict/eta", summary="Predict delivery ETA (minutes)")
def predict_eta(request: EtaRequest,
                cfg: ApiConfig = Depends(get_config)) -> dict:
    if not eta_model_info(cfg):
        raise HTTPException(503, "ETA model is not registered yet; "
                                 "run ml.train_eta first.")
    try:
        from ml.predict import EtaPredictor

        predictor = EtaPredictor.get(cfg.mlflow_tracking_uri,
                                     cfg.eta_interval_half_min)
        result = predictor.predict(request.model_dump())
    except Exception as exc:
        log.exception("ETA prediction failed")
        raise HTTPException(500, f"Prediction failed: {exc}") from exc
    log.info("eta prediction: %.2f min (model v%s)",
             result["predicted_eta_minutes"], result.get("model_version"))
    return result


@router.post("/predict/anomaly", response_model=list[AnomalyPrediction],
             summary="Score telemetry rows with the Isolation Forest")
def predict_anomaly(request: AnomalyRequest,
                    cfg: ApiConfig = Depends(get_config)) -> list[AnomalyPrediction]:
    if not anomaly_model_info(cfg):
        raise HTTPException(503, "Anomaly model is not registered yet; "
                                 "run ml.train_anomaly first.")
    try:
        from pathlib import Path

        from ml.predict import AnomalyPredictor

        scaler_path = Path(cfg.anomaly_meta_dir) / "anomaly_scaler.joblib"
        predictor = AnomalyPredictor.get(cfg.mlflow_tracking_uri, scaler_path)
        rows = predictor.predict(request.observations)
    except Exception as exc:
        log.exception("Anomaly prediction failed")
        raise HTTPException(500, f"Prediction failed: {exc}") from exc
    log.info("anomaly prediction: %s rows (%s flagged)",
             len(rows), sum(1 for r in rows if r["anomaly_flag"]))
    return [AnomalyPrediction(**r) for r in rows]
