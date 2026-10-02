"""Fleet + KPI endpoints."""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import ApiConfig, get_config
from api.schemas import KpiResponse, VehicleCard, VehicleDetail
from api.services.store import GoldStore

log = logging.getLogger("api.fleet")

router = APIRouter(prefix="/api", tags=["fleet"])

_store: Optional[GoldStore] = None


def store(cfg: ApiConfig = Depends(get_config)) -> GoldStore:
    global _store
    if _store is None or _store.cfg != cfg:
        _store = GoldStore(cfg)
    return _store


@router.get("/kpis", response_model=KpiResponse,
            summary="Current operational KPIs from gold data")
def get_kpis(s: GoldStore = Depends(store)) -> KpiResponse:
    kpis = s.read("fleet_kpis")
    deliveries = s.read("delivery_performance")
    anomalies = s.read("anomalies")

    latest = None
    if not kpis.empty and "window_start" in kpis.columns:
        kpis = kpis.sort_values("window_start")
        latest = kpis.iloc[-1]
    total_deliveries = int(deliveries["completed_deliveries"].sum()) if not deliveries.empty else 0
    on_time = float(deliveries["on_time"].sum()) if not deliveries.empty else None
    on_time_rate = (on_time / total_deliveries) if total_deliveries else None
    n_anomalies = (int(anomalies["anomaly_flag"].sum())
                   if not anomalies.empty and "anomaly_flag" in anomalies.columns else 0)
    return KpiResponse(
        active_vehicles=int(latest["active_vehicles"]) if latest is not None else 0,
        total_deliveries=total_deliveries,
        on_time_rate=round(on_time_rate, 4) if on_time_rate is not None else None,
        avg_duration_minutes=None,
        detected_anomalies=n_anomalies,
        avg_fuel_rate_lph=round(float(latest["avg_fuel_rate_lph"]), 2) if latest is not None else None,
        window_start=str(latest["window_start"]) if latest is not None else None,
    )


@router.get("/kpis/series", summary="KPI time series (5-minute windows)")
def kpi_series(limit: int = Query(288, ge=1, le=2000),
               s: GoldStore = Depends(store)) -> dict:
    kpis = s.read("fleet_kpis")
    if kpis.empty or "window_start" not in kpis.columns:
        return {"series": [], "note": "No KPI series available."}
    kpis = kpis.sort_values("window_start").tail(limit)
    series = []
    for _, row in kpis.iterrows():
        series.append({
            "window_start": str(row["window_start"]),
            "active_vehicles": int(row["active_vehicles"]),
            "avg_speed_kmh": round(float(row["avg_speed_kmh"]), 2),
            "avg_fuel_rate_lph": round(float(row["avg_fuel_rate_lph"]), 3),
            "total_distance_km": round(float(row["total_distance_km"]), 2),
            "total_idle_s": round(float(row["total_idle_s"]), 1),
        })
    return {"series": series}


@router.get("/fleet/summary",
            summary="Fleet summary: counts + status breakdown")
def fleet_summary(s: GoldStore = Depends(store)) -> dict:
    snap = s.read("vehicle_snapshot")
    anomalies = s.read("anomalies")
    if snap.empty:
        return {"vehicles_total": 0, "vehicles_active": 0, "vehicles_inactive": 0,
                "detected_anomalies": 0, "note": "No gold data available; "
                "run the pipeline (README) to populate data_lake/gold."}
    active = int((snap["status"] == "active").sum())
    n_anomalies = (int(anomalies["anomaly_flag"].sum())
                   if not anomalies.empty and "anomaly_flag" in anomalies.columns else 0)
    return {
        "vehicles_total": int(len(snap)),
        "vehicles_active": active,
        "vehicles_inactive": int(len(snap)) - active,
        "detected_anomalies": n_anomalies,
        "vehicle_types": (snap["vehicle_type"].value_counts().to_dict()
                          if "vehicle_type" in snap.columns else {}),
    }


@router.get("/fleet/vehicles", response_model=list[VehicleCard],
            summary="Vehicle list with search / filter / sort / pagination")
def list_vehicles(
    search: Optional[str] = Query(None, description="substring match on vehicle_id"),
    status: Optional[str] = Query(None, description="active | inactive"),
    vehicle_type: Optional[str] = Query(None),
    sort_by: str = Query("vehicle_id", description="column name"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    s: GoldStore = Depends(store),
) -> list[VehicleCard]:
    df = s.read("vehicle_snapshot")
    if df.empty:
        return []
    if search:
        df = df[df["vehicle_id"].str.contains(search, case=False, na=False)]
    if status:
        df = df[df["status"] == status]
    if vehicle_type and "vehicle_type" in df.columns:
        df = df[df["vehicle_type"] == vehicle_type]
    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=(order == "asc"))
    page = df.iloc[offset:offset + limit]
    return [VehicleCard(
        vehicle_id=row["vehicle_id"],
        status=row["status"],
        vehicle_type=row.get("vehicle_type"),
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
        speed_kmh=round(float(row["speed_kmh"]), 1) if pd.notna(row.get("speed_kmh")) else None,
        fuel_rate_lph=round(float(row["fuel_rate_lph"]), 2) if pd.notna(row.get("fuel_rate_lph")) else None,
        fuel_level_pct=round(float(row["fuel_level_pct"]), 1) if pd.notna(row.get("fuel_level_pct")) else None,
        route_id=row.get("route_id"),
        last_seen=str(row.get("last_seen")),
        engine_temp_c=round(float(row["engine_temp_c"]), 1) if pd.notna(row.get("engine_temp_c")) else None,
        age_years=row.get("age_years"),
    ) for _, row in page.iterrows()]


@router.get("/fleet/vehicles/{vehicle_id}", response_model=VehicleDetail,
            summary="Vehicle detail: current state + history series")
def vehicle_detail(vehicle_id: str, s: GoldStore = Depends(store)) -> VehicleDetail:
    snap = s.read("vehicle_snapshot")
    if snap.empty or vehicle_id not in set(snap["vehicle_id"]):
        raise HTTPException(404, f"vehicle {vehicle_id} not found in gold data")
    row = snap[snap["vehicle_id"] == vehicle_id].iloc[0].to_dict()
    row = {k: (None if pd.isna(v) else v) for k, v in row.items()}

    tele = s.read_raw("telemetry.parquet")
    history_speed, history_fuel, history_idle = [], [], []
    if not tele.empty and "vehicle_id" in tele.columns:
        vt = tele[tele["vehicle_id"] == vehicle_id].tail(500)
        history_speed = [{"t": str(t), "speed_kmh": float(v)}
                         for t, v in zip(vt["timestamp"], vt["speed_kmh"], strict=False)]
        history_fuel = [{"t": str(t), "fuel_rate_lph": float(v)}
                        for t, v in zip(vt["timestamp"], vt["fuel_rate_lph"], strict=False)]
        history_idle = [{"t": str(t), "idle_time_s": float(v)}
                        for t, v in zip(vt["timestamp"], vt["idle_time_s"], strict=False)]

    anomalies = s.read("anomalies")
    anomaly_score = None
    if not anomalies.empty and "vehicle_id" in anomalies.columns:
        v_anom = anomalies[anomalies["vehicle_id"] == vehicle_id]
        if not v_anom.empty:
            anomaly_score = float(v_anom["anomaly_raw_score"].max())

    return VehicleDetail(vehicle_id=vehicle_id, current=row,
                         history_speed=history_speed, history_fuel=history_fuel,
                         history_idle=history_idle, anomaly_score=anomaly_score)
