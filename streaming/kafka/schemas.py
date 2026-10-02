"""Pydantic event schemas for the three Kafka topics.

These models serve two purposes:
1. Documentation of the wire format (JSON over Kafka).
2. Validation: every event is validated before it is produced, and again
   when it is consumed by the Spark layer. Invalid events are rejected at
   the edge and counted in the quality report — they never silently
   disappear.

Field naming is snake_case for Python friendliness; Spark maps them 1:1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

TOPIC_TELEMETRY = "fleet.telemetry"
TOPIC_GPS = "fleet.gps"
TOPIC_DELIVERY = "fleet.delivery"

EVENT_TYPE_TO_TOPIC = {
    "telemetry": TOPIC_TELEMETRY,
    "gps": TOPIC_GPS,
    "delivery": TOPIC_DELIVERY,
}


class TelemetryEvent(BaseModel):
    """Vehicle telemetry emitted every simulation tick while active."""

    event_id: str
    vehicle_id: str = Field(pattern=r"^V\d{5}$")
    driver_id: str = Field(pattern=r"^D\d{5}$")
    route_id: Optional[str] = Field(default=None, pattern=r"^R\d{3}$")
    timestamp: datetime
    speed_kmh: float = Field(ge=0, le=200)
    fuel_rate_lph: float = Field(ge=0, le=120)
    fuel_level_pct: float = Field(ge=0, le=100)
    engine_load_pct: float = Field(ge=0, le=100)
    engine_temp_c: float = Field(ge=-20, le=180)
    ambient_temp_c: float = Field(ge=-60, le=70)
    mileage_km: float = Field(ge=0)
    idle_time_s: float = Field(ge=0, le=3600)
    weather: Literal["clear", "rain", "storm"]
    traffic_multiplier: float = Field(ge=0, le=10)
    event_type: Literal["telemetry"]


class GpsEvent(BaseModel):
    """GPS fix with coordinates inside the simulated region bounding box."""

    event_id: str
    vehicle_id: str = Field(pattern=r"^V\d{5}$")
    route_id: Optional[str] = Field(default=None, pattern=r"^R\d{3}$")
    timestamp: datetime
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(ge=0, le=1000)
    event_type: Literal["gps"]


class DeliveryEvent(BaseModel):
    """Delivery lifecycle status update."""

    event_id: str
    delivery_id: str = Field(pattern=r"^DLV-\d{6}$")
    vehicle_id: Optional[str] = Field(default=None, pattern=r"^V\d{5}$")
    route_id: str = Field(pattern=r"^R\d{3}$")
    stop_index: int = Field(ge=0, le=100)
    timestamp: datetime
    status: Literal["OUT_FOR_DELIVERY", "DELIVERED", "DELAYED", "FAILED"]
    planned_arrival_time: Optional[datetime] = None
    parcels: int = Field(ge=0, le=10000)
    weather: Literal["clear", "rain", "storm"]
    event_type: Literal["delivery"]

    @field_validator("planned_arrival_time", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v):
        return None if v in ("", None) else v


def schema_for_event_type(event_type: str) -> type[BaseModel]:
    """Return the Pydantic model that validates a given event type."""
    if event_type == "telemetry":
        return TelemetryEvent
    if event_type == "gps":
        return GpsEvent
    if event_type == "delivery":
        return DeliveryEvent
    raise ValueError(f"Unknown event type: {event_type!r}")


def topic_for_event(event: dict) -> str:
    """Map an event dict to its Kafka topic (raises on unknown type)."""
    event_type = event.get("event_type")
    if event_type not in EVENT_TYPE_TO_TOPIC:
        raise ValueError(f"Unknown event type: {event_type!r}")
    return EVENT_TYPE_TO_TOPIC[event_type]


def validate_event(event: dict) -> BaseModel:
    """Validate a raw event dict; raises pydantic.ValidationError if invalid."""
    return schema_for_event_type(event["event_type"]).model_validate(event)
