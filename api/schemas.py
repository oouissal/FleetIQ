"""Pydantic models for FleetIQ API responses/requests."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- requests
class EtaRequest(BaseModel):
    distance_km: float = Field(gt=0, le=5000,
                               description="Planned trip distance to the stop.")
    vehicle_type: Literal["VAN", "BOX_TRUCK", "SEMI_TRAILER", "REFRIGERATED"] = "BOX_TRUCK"
    route_id: Optional[str] = Field(default=None, pattern=r"^R\d{3}$")
    origin: Optional[str] = Field(default=None, max_length=120)
    destination: Optional[str] = Field(default=None, max_length=120)
    dispatch_time: Optional[str] = Field(default=None,
                                         description="ISO-8601; defaults to now (UTC).")
    congestion_factor: Optional[float] = Field(default=None, ge=0.2, le=5.0)
    historical_route_duration_min: Optional[float] = Field(default=None, gt=0)
    weather: Literal["clear", "rain", "storm"] = "clear"
    parcels: Optional[int] = Field(default=None, ge=0, le=10000)
    stop_index: Optional[int] = Field(default=None, ge=0, le=100)


class AnomalyRequest(BaseModel):
    """One or more telemetry rows to score with the Isolation Forest."""

    observations: list[dict[str, float]] = Field(
        min_length=1, max_length=100,
        description="Rows with keys: speed_kmh, acceleration_kmh_s, "
                    "fuel_rate_lph, engine_load_pct, engine_temp_c, "
                    "ambient_temp_c, idle_time_s")


class AnomalyPrediction(BaseModel):
    anomaly_score: float
    anomaly_flag: bool
    description: str


# ---------------------------------------------------------------- responses
class HealthResponse(BaseModel):
    status: str
    service: str = "fleetiq-api"
    data_available: bool
    models_available: bool


class KpiResponse(BaseModel):
    active_vehicles: int
    total_deliveries: int
    on_time_rate: Optional[float]
    avg_duration_minutes: Optional[float]
    detected_anomalies: int
    avg_fuel_rate_lph: Optional[float]
    window_start: Optional[str]
    note: str = "Computed from the latest available gold data (synthetic)."


class VehicleCard(BaseModel):
    vehicle_id: str
    status: str
    vehicle_type: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    speed_kmh: Optional[float]
    fuel_rate_lph: Optional[float]
    fuel_level_pct: Optional[float]
    route_id: Optional[str]
    last_seen: Optional[str]
    engine_temp_c: Optional[float]
    age_years: Optional[float]


class VehicleDetail(BaseModel):
    vehicle_id: str
    current: dict[str, Any]
    history_speed: list[dict[str, Any]]
    history_fuel: list[dict[str, Any]]
    history_idle: list[dict[str, Any]]
    anomaly_score: Optional[float]
    note: str = "History series are the last 500 telemetry events (synthetic)."
