"""Domain models and constants for the FleetIQ synthetic data generator.

All data generated from these models is SYNTHETIC. The hub names, vehicle IDs,
driver names and coordinates are invented and do not correspond to any real
company, fleet, or person. Coordinates describe a fictional metro region.

Assumptions (documented for transparency):
- 1 driver per vehicle, single shift per driver per day (06:00-20:00).
- Telemetry and GPS events are emitted every 10 simulated seconds while a
  vehicle is active.
- Routes are fixed polylines between fictional hubs; distance is computed with
  an equirectangular approximation (valid for a small region).
- Vehicle age increases anomaly injection probability (see simulation.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VehicleType(str, Enum):
    VAN = "VAN"
    BOX_TRUCK = "BOX_TRUCK"
    SEMI_TRAILER = "SEMI_TRAILER"
    REFRIGERATED = "REFRIGERATED"


class DeliveryStatus(str, Enum):
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    DELAYED = "DELAYED"
    FAILED = "FAILED"


class AnomalyKind(str, Enum):
    """Anomaly types injected into the synthetic telemetry stream.

    These labels exist ONLY to let us verify the unsupervised anomaly detector
    on ground truth. The detection model itself never sees them.
    """

    NONE = "none"
    TEMP_DRIFT = "temp_drift"
    FUEL_ANOMALY = "fuel_anomaly"
    ENGINE_OVERLOAD = "engine_overload"
    SPEED_SENSOR_NOISE = "speed_sensor_noise"


class Weather(str, Enum):
    CLEAR = "clear"
    RAIN = "rain"
    STORM = "storm"


# ---------------------------------------------------------------------------
# Geography constants (fictional region)
# ---------------------------------------------------------------------------
REGION_CENTER_LAT = 45.42
REGION_CENTER_LON = -73.62
REGION_RADIUS_DEG = 0.9  # ~100 km

HUB_NAMES = [
    "Northgate DC",
    "Riverside Hub",
    "Eastport Depot",
    "Westfield DC",
    "Central Terminal",
    "Lakeside Hub",
    "Airport Depot",
    "Harbor DC",
    "Midtown Depot",
    "Hillcrest Hub",
    "Orchard DC",
    "Summit Depot",
    "Brookline Hub",
    "Fairview DC",
    "Clover Depot",
    "Ironworks Hub",
    "Maple DC",
    "Pinewood Depot",
    "Quarry Hub",
    "Rosewood DC",
    "Stonebridge Hub",
    "Twin Peaks Depot",
    "Union Square DC",
    "Vineyard Hub",
    "Wharfside Depot",
]

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON = 111.320  # at equator; scaled by cos(lat)


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float

    def distance_km(self, other: "GeoPoint") -> float:
        """Equirectangular approximation, valid for this small region."""
        lat_mean = math.radians((self.latitude + other.latitude) / 2.0)
        dx = (other.longitude - self.longitude) * KM_PER_DEG_LON * math.cos(lat_mean)
        dy = (other.latitude - self.latitude) * KM_PER_DEG_LAT
        return math.hypot(dx, dy)


@dataclass
class Hub:
    hub_id: str
    name: str
    location: GeoPoint


@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: VehicleType
    age_years: float
    base_speed_kmh: float  # cruise speed on open road
    fuel_efficiency: float  # base l/100km at cruise
    anomaly_profile: AnomalyKind  # pre-assigned tendency
    anomaly_risk: float  # probability per trip, scaled by age


@dataclass
class Driver:
    driver_id: str
    vehicle_id: str
    shift_start_hour: int
    shift_duration_hours: int
    behavior: str  # cautious | normal | aggressive


@dataclass
class Route:
    route_id: str
    origin_hub_id: str
    destination_hub_id: str
    waypoints: list[GeoPoint]
    distance_km: float
    congestion_factor: float  # 0.5 (light) .. 2.5 (chronic)
    typical_duration_min: float


@dataclass
class Delivery:
    delivery_id: str
    route_id: str
    stop_index: int
    stop_fraction: float  # position along the route 0..1
    parcels: int
    vehicle_id: Optional[str] = None  # claimed by a vehicle at trip assignment
    planned_dispatch_time: Optional[str] = None  # ISO timestamp
    planned_arrival_time: Optional[str] = None
    actual_arrival_time: Optional[str] = None
    status: Optional[DeliveryStatus] = None
    leg_distance_km: float = 0.0
    duration_minutes: Optional[float] = None
    delayed: Optional[bool] = None
    weather: Optional[Weather] = None
    traffic_multiplier: Optional[float] = None


@dataclass
class SimConfig:
    seed: int
    start_time_iso: str
    sim_days: int
    dt_seconds: int = 10
    max_events: int = 300_000
