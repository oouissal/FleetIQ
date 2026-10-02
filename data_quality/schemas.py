"""Pandera schemas for the three FleetIQ event domains.

These mirror the declarative rules in streaming/spark/validation.py, but
target pandas DataFrames (batch/historical path + quality reports). The
Spark streaming pipeline applies the equivalent rules row-by-row.

Ranges and formats match the generator and are documented in
docs/data-lake.md.
"""

from __future__ import annotations

import pandera as pa
from pandera.typing import Series


class TelemetrySchema(pa.DataFrameModel):
    """One row per telemetry event (10s tick while active)."""

    event_id: Series[str] = pa.Field(nullable=False, unique=False)
    vehicle_id: Series[str] = pa.Field(nullable=False, str_matches=r"^V\d{5}$")
    driver_id: Series[str] = pa.Field(nullable=True, str_matches=r"^D\d{5}$")
    route_id: Series[str] = pa.Field(nullable=True, str_matches=r"^R\d{3}$")
    timestamp: Series[str] = pa.Field(nullable=False)
    speed_kmh: Series[float] = pa.Field(nullable=False, ge=0, le=200)
    fuel_rate_lph: Series[float] = pa.Field(nullable=False, ge=0, le=120)
    fuel_level_pct: Series[float] = pa.Field(nullable=False, ge=0, le=100)
    engine_load_pct: Series[float] = pa.Field(nullable=False, ge=0, le=100)
    engine_temp_c: Series[float] = pa.Field(nullable=False, ge=-20, le=180)
    ambient_temp_c: Series[float] = pa.Field(nullable=False, ge=-60, le=70)
    mileage_km: Series[float] = pa.Field(nullable=False, ge=0)
    idle_time_s: Series[float] = pa.Field(nullable=False, ge=0, le=3600)
    dt_seconds: Series[int] = pa.Field(nullable=False, ge=1, le=3600)
    weather: Series[str] = pa.Field(nullable=False, isin=["clear", "rain", "storm"])
    traffic_multiplier: Series[float] = pa.Field(nullable=False, ge=0, le=10)
    event_type: Series[str] = pa.Field(nullable=False, isin=["telemetry"])

    class Config:
        strict = False
        coerce = False


class GpsSchema(pa.DataFrameModel):
    """One row per GPS fix."""

    event_id: Series[str] = pa.Field(nullable=False)
    vehicle_id: Series[str] = pa.Field(nullable=False, str_matches=r"^V\d{5}$")
    route_id: Series[str] = pa.Field(nullable=True, str_matches=r"^R\d{3}$")
    timestamp: Series[str] = pa.Field(nullable=False)
    latitude: Series[float] = pa.Field(nullable=False, ge=-90, le=90)
    longitude: Series[float] = pa.Field(nullable=False, ge=-180, le=180)
    accuracy_m: Series[float] = pa.Field(nullable=False, ge=0, le=1000)
    event_type: Series[str] = pa.Field(nullable=False, isin=["gps"])

    class Config:
        strict = False
        coerce = False


class DeliverySchema(pa.DataFrameModel):
    """One row per delivery lifecycle update."""

    delivery_id: Series[str] = pa.Field(nullable=False, str_matches=r"^DLV-\d{6}$")
    route_id: Series[str] = pa.Field(nullable=False, str_matches=r"^R\d{3}$")
    vehicle_id: Series[str] = pa.Field(nullable=True, str_matches=r"^V\d{5}$")
    stop_index: Series[int] = pa.Field(nullable=True, ge=0, le=100)
    timestamp: Series[str] = pa.Field(nullable=False)
    status: Series[str] = pa.Field(
        nullable=False, isin=["OUT_FOR_DELIVERY", "DELIVERED", "DELAYED", "FAILED"])
    planned_arrival_time: Series[str] = pa.Field(nullable=True)
    parcels: Series[int] = pa.Field(nullable=False, ge=0, le=10000)
    weather: Series[str] = pa.Field(nullable=True, isin=["clear", "rain", "storm"])
    event_type: Series[str] = pa.Field(nullable=False, isin=["delivery"])

    class Config:
        strict = False
        coerce = False


SCHEMAS_BY_TYPE = {
    "telemetry": TelemetrySchema,
    "gps": GpsSchema,
    "delivery": DeliverySchema,
}


def schema_for(event_type: str) -> type[pa.DataFrameModel]:
    if event_type not in SCHEMAS_BY_TYPE:
        raise ValueError(f"Unknown event type: {event_type!r}")
    return SCHEMAS_BY_TYPE[event_type]
