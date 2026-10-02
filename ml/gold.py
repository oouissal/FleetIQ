"""Batch gold-layer builder (pandas).

Produces the SAME gold schemas as the Spark streaming job
(streaming/spark/aggregates.py), so the API can serve either:

    * gold tables produced by Spark Structured Streaming (Docker path), or
    * gold tables produced by this batch builder (local dev + Airflow DAG).

Both are written as parquet under data_lake/gold/. The batch builder is NOT
a silent replacement for Spark — it exists for development, CI and the
Airflow batch pipeline, and the README documents the difference.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger("ml.gold")

WINDOW = "5min"


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s)


def build_fleet_kpis(telemetry: pd.DataFrame) -> pd.DataFrame:
    """5-minute global KPIs (same schema as Spark gold/fleet_kpis)."""
    t = telemetry.copy()
    t["timestamp"] = _ts(t["timestamp"])
    t["window_start"] = t["timestamp"].dt.floor(WINDOW)
    t["distance_km"] = t["speed_kmh"] * t["dt_seconds"] / 3600.0
    return (t.groupby("window_start")
            .agg(active_vehicles=("vehicle_id", "nunique"),
                 avg_speed_kmh=("speed_kmh", "mean"),
                 avg_fuel_rate_lph=("fuel_rate_lph", "mean"),
                 total_distance_km=("distance_km", "sum"),
                 total_idle_s=("idle_time_s", "sum"),
                 telemetry_events=("event_id", "count"))
            .reset_index())


def build_route_performance(telemetry: pd.DataFrame) -> pd.DataFrame:
    """5-minute per-route performance (same schema as Spark gold)."""
    t = telemetry[telemetry["route_id"].notna()].copy()
    t["timestamp"] = _ts(t["timestamp"])
    t["window_start"] = t["timestamp"].dt.floor(WINDOW)
    t["distance_km"] = t["speed_kmh"] * t["dt_seconds"] / 3600.0
    t["fuel_per_100km"] = t["fuel_rate_lph"] * 100.0 / t["speed_kmh"].where(t["speed_kmh"] > 5)
    return (t.groupby(["window_start", "route_id"])
            .agg(vehicles_on_route=("vehicle_id", "nunique"),
                 avg_speed_kmh=("speed_kmh", "mean"),
                 avg_traffic_multiplier=("traffic_multiplier", "mean"),
                 avg_fuel_per_100km=("fuel_per_100km", "mean"),
                 total_distance_km=("distance_km", "sum"),
                 total_idle_s=("idle_time_s", "sum"),
                 telemetry_events=("event_id", "count"))
            .reset_index())


def build_vehicle_health(telemetry: pd.DataFrame) -> pd.DataFrame:
    """5-minute per-vehicle health (same schema as Spark gold)."""
    t = telemetry.copy()
    t["timestamp"] = _ts(t["timestamp"])
    t["window_start"] = t["timestamp"].dt.floor(WINDOW)
    t["fuel_l"] = t["fuel_rate_lph"] * t["dt_seconds"] / 3600.0
    agg = (t.groupby(["window_start", "vehicle_id"])
           .agg(avg_speed_kmh=("speed_kmh", "mean"),
                max_speed_kmh=("speed_kmh", "max"),
                speed_stddev_kmh=("speed_kmh", "std"),
                avg_engine_load_pct=("engine_load_pct", "mean"),
                max_engine_temp_c=("engine_temp_c", "max"),
                total_idle_s=("idle_time_s", "sum"),
                fuel_l=("fuel_l", "sum"),
                telemetry_events=("event_id", "count"))
           .reset_index())
    agg["idle_ratio"] = agg["total_idle_s"] / (agg["telemetry_events"] * 10.0)
    agg["attention_flag"] = np.select(
        [agg["max_engine_temp_c"] > 112.0,
         agg["avg_engine_load_pct"] > 92.0,
         agg["idle_ratio"] > 0.6],
        ["temp_alert", "engine_load_alert", "excess_idle"], default="ok")
    return agg.drop(columns=["idle_ratio"])


def build_delivery_performance(deliveries: pd.DataFrame) -> pd.DataFrame:
    """5-minute per-route delivery performance (same schema as Spark gold)."""
    d = deliveries[deliveries["status"].isin(["DELIVERED", "DELAYED", "FAILED"])].copy()
    d["timestamp"] = _ts(d["actual_arrival_time"])
    d["window_start"] = d["timestamp"].dt.floor(WINDOW)
    planned = _ts(d["planned_arrival_time"])
    d["delay_minutes"] = (d["timestamp"] - planned).dt.total_seconds() / 60.0
    agg = (d.groupby(["window_start", "route_id"])
           .agg(completed_deliveries=("delivery_id", "count"),
                on_time=("status", lambda s: int((s == "DELIVERED").sum())),
                delayed=("status", lambda s: int((s == "DELAYED").sum())),
                failed=("status", lambda s: int((s == "FAILED").sum())),
                avg_delay_minutes=("delay_minutes", "mean"))
           .reset_index())
    agg["on_time_rate"] = agg["on_time"] / agg["completed_deliveries"]
    return agg


def build_vehicle_snapshot(telemetry: pd.DataFrame, gps: pd.DataFrame,
                           vehicles: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Latest known state per vehicle (serves the Fleet page).

    Status is DERIVED from data: a vehicle is "active" if it has telemetry
    within the last 30 minutes of its own timeline, otherwise "inactive".
    """
    t = telemetry.copy()
    t["timestamp"] = _ts(t["timestamp"])
    latest_tele = t.sort_values("timestamp").groupby("vehicle_id").tail(1)
    latest_tele = latest_tele[["vehicle_id", "timestamp", "speed_kmh",
                               "fuel_rate_lph", "fuel_level_pct",
                               "engine_temp_c", "mileage_km", "route_id",
                               "weather", "traffic_multiplier"]].rename(
        columns={"timestamp": "last_seen"})

    g = gps.copy()
    g["timestamp"] = _ts(g["timestamp"])
    latest_gps = g.sort_values("timestamp").groupby("vehicle_id").tail(1)
    latest_gps = latest_gps[["vehicle_id", "latitude", "longitude"]]

    snap = latest_tele.merge(latest_gps, on="vehicle_id", how="left")
    max_ts = latest_tele["last_seen"].max()
    snap["status"] = np.where(
        (max_ts - snap["last_seen"]) <= pd.Timedelta(minutes=30), "active", "inactive")
    if vehicles is not None:
        snap = snap.merge(vehicles[["vehicle_id", "vehicle_type", "age_years"]],
                          on="vehicle_id", how="left")
    return snap.reset_index(drop=True)


def build_all(raw_dir: Path, gold_dir: Path) -> dict[str, int]:
    """Build every gold table from raw parquet files; returns row counts."""
    gold_dir.mkdir(parents=True, exist_ok=True)
    telemetry = pd.read_parquet(raw_dir / "telemetry.parquet")
    gps = pd.read_parquet(raw_dir / "gps.parquet")
    deliveries = pd.read_parquet(raw_dir / "deliveries.parquet")
    vehicles = pd.read_parquet(raw_dir / "vehicles.parquet")

    outputs = {
        "fleet_kpis": build_fleet_kpis(telemetry),
        "route_performance": build_route_performance(telemetry),
        "vehicle_health": build_vehicle_health(telemetry),
        "delivery_performance": build_delivery_performance(deliveries),
        "vehicle_snapshot": build_vehicle_snapshot(telemetry, gps, vehicles),
    }
    counts = {}
    for name, df in outputs.items():
        df.to_parquet(gold_dir / f"{name}.parquet", index=False)
        counts[name] = len(df)
        log.info("gold/%s: %s rows", name, len(df))
    return counts
