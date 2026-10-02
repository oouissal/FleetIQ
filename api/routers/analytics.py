"""Routes + deliveries endpoints."""

from __future__ import annotations

from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, Query

from api.routers.fleet import store
from api.services.store import GoldStore

router = APIRouter(prefix="/api", tags=["analytics"])


def _json_rows(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    out = []
    for _, row in df.iterrows():
        item = {}
        for c in cols:
            v = row.get(c)
            item[c] = None if v is None or (isinstance(v, float) and pd.isna(v)) \
                else (str(v) if isinstance(v, (pd.Timestamp,)) else
                      (float(v) if isinstance(v, (int, float)) else v))
        out.append(item)
    return out


@router.get("/routes", summary="Route list + aggregate performance")
def list_routes(
    limit: int = Query(100, ge=1, le=500),
    sort_by: str = Query("avg_speed_kmh"),
    s: GoldStore = Depends(store),
) -> dict:
    perf = s.read("route_performance")
    routes_raw = s.read_raw("routes.parquet")
    if perf.empty:
        return {"routes": [], "note": "No route performance data available."}
    # aggregate across windows per route
    agg = (perf.groupby("route_id")
           .agg(avg_speed_kmh=("avg_speed_kmh", "mean"),
                avg_traffic_multiplier=("avg_traffic_multiplier", "mean"),
                avg_fuel_per_100km=("avg_fuel_per_100km", "mean"),
                total_distance_km=("total_distance_km", "sum"),
                windows=("route_id", "count"))
           .reset_index())
    if not routes_raw.empty:
        agg = agg.merge(routes_raw[["route_id", "distance_km", "congestion_factor",
                                    "typical_duration_min"]], on="route_id", how="left")
    agg = agg.sort_values(sort_by, ascending=False).head(limit)
    return {"routes": _json_rows(agg, list(agg.columns)),
            "note": "Aggregates over 5-minute windows from gold data."}


@router.get("/deliveries", summary="Deliveries with status filters")
def list_deliveries(
    status: Optional[str] = Query(None, description="DELIVERED | DELAYED | FAILED"),
    route_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    s: GoldStore = Depends(store),
) -> dict:
    deliveries = s.read_raw("deliveries.parquet")
    if deliveries.empty:
        return {"deliveries": [], "total": 0,
                "note": "No delivery data available."}
    if status:
        deliveries = deliveries[deliveries["status"] == status]
    if route_id:
        deliveries = deliveries[deliveries["route_id"] == route_id]
    deliveries = deliveries.sort_values("actual_arrival_time", ascending=False)
    total = int(len(deliveries))
    page = deliveries.head(limit)
    cols = ["delivery_id", "vehicle_id", "route_id", "status",
            "planned_arrival_time", "actual_arrival_time",
            "duration_minutes", "delayed", "weather"]
    return {"deliveries": _json_rows(page, cols), "total": total}
