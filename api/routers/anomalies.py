"""Anomaly center endpoints."""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, Query

from api.routers.fleet import store
from api.services.store import GoldStore

router = APIRouter(prefix="/api", tags=["anomalies"])


@router.get("/anomalies", summary="Detected anomalies (unsupervised)")
def list_anomalies(
    vehicle_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=2000),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    s: GoldStore = Depends(store),
) -> dict:
    df = s.read("anomalies")
    if df.empty or "anomaly_flag" not in df.columns:
        return {"anomalies": [], "count": 0,
                "note": "No anomaly scoring available; run ml.train_anomaly."}
    flagged = df[df["anomaly_flag"]].copy()
    if vehicle_id:
        flagged = flagged[flagged["vehicle_id"] == vehicle_id]
    if "anomaly_raw_score" in flagged.columns:
        flagged = flagged[flagged["anomaly_raw_score"] >= min_score]
        flagged = flagged.sort_values("anomaly_raw_score", ascending=False)
    else:
        flagged = flagged.sort_values("anomaly_score", ascending=True)
    total = int(len(flagged))
    page = flagged.head(limit)

    out = []
    for _, row in page.iterrows():
        types = row.get("anomaly_type")
        if isinstance(types, (list,)) :
            pattern = types
        elif isinstance(types, str) and types:
            pattern = [types]
        else:
            pattern = []
        out.append({
            "vehicle_id": row.get("vehicle_id"),
            "timestamp": str(row.get("timestamp")),
            "anomaly_score": round(float(row["anomaly_raw_score"]), 3)
            if pd.notna(row.get("anomaly_raw_score")) else None,
            "pattern": pattern,
            "description": "Unusual telemetry pattern detected. "
                           "(Pattern describes the deviating measurements; "
                           "not a diagnosed fault.)",
            "signals": {k: (round(float(row[k]), 2) if pd.notna(row.get(k)) else None)
                        for k in ("speed_kmh", "fuel_rate_lph", "engine_load_pct",
                                  "engine_temp_c", "idle_time_s")
                        if k in row.index},
        })
    return {"anomalies": out, "count": total}
