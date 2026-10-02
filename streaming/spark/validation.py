"""Declarative data-quality rules for the streaming pipeline.

Every rule exists in two equivalent forms:

* ``expr``   — a Spark SQL boolean expression applied to event columns.
* ``py``     — a pure-Python predicate over a plain dict, so the exact same
              rules are unit-testable without a Spark session.

Rules are grouped per event type. In the pipeline, all failing rule names
are collected into a ``validation_errors`` array column; rows with a
non-empty array are routed to ``bronze/_invalid/<type>`` (they never
silently disappear) and counted into the data-quality report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

VEHICLE_ID_RE = re.compile(r"^V\d{5}$")
DRIVER_ID_RE = re.compile(r"^D\d{5}$")
ROUTE_ID_RE = re.compile(r"^R\d{3}$")
DELIVERY_ID_RE = re.compile(r"^DLV-\d{6}$")


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    expr: str  # Spark SQL boolean expression
    py: Callable[[dict], bool]  # pure-python equivalent


def _num(d: dict, key: str):
    v = d.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ts(d: dict, key: str):
    v = d.get(key)
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Rule sets
# ---------------------------------------------------------------------------
def _telemetry_rules() -> list[Rule]:
    def in_range(key, lo, hi):
        def _f(d):
            v = _num(d, key)
            return v is not None and lo <= v <= hi
        return _f

    return [
        Rule("event_id_present", "event_id is a non-empty string",
             "event_id IS NOT NULL AND event_id <> ''",
             lambda d: isinstance(d.get("event_id"), str) and bool(d["event_id"])),
        Rule("vehicle_id_pattern", "vehicle_id matches V#####",
             "vehicle_id IS NOT NULL AND vehicle_id RLIKE '^V\\\\d{5}$'",
             lambda d: isinstance(d.get("vehicle_id"), str)
             and bool(VEHICLE_ID_RE.match(d["vehicle_id"]))),
        Rule("driver_id_pattern", "driver_id matches D##### or is null",
             "driver_id IS NULL OR driver_id RLIKE '^D\\\\d{5}$'",
             lambda d: d.get("driver_id") is None
             or (isinstance(d.get("driver_id"), str)
                 and bool(DRIVER_ID_RE.match(d["driver_id"])))),
        Rule("route_id_pattern", "route_id matches R### or is null",
             "route_id IS NULL OR route_id RLIKE '^R\\\\d{3}$'",
             lambda d: d.get("route_id") is None
             or (isinstance(d.get("route_id"), str)
                 and bool(ROUTE_ID_RE.match(d["route_id"])))),
        Rule("timestamp_valid", "timestamp parses as ISO-8601",
             "timestamp IS NOT NULL",
             lambda d: _ts(d, "timestamp") is not None),
        Rule("speed_range", "0 <= speed_kmh <= 200",
             "speed_kmh IS NOT NULL AND speed_kmh >= 0 AND speed_kmh <= 200",
             in_range("speed_kmh", 0, 200)),
        Rule("fuel_rate_range", "0 <= fuel_rate_lph <= 120",
             "fuel_rate_lph IS NOT NULL AND fuel_rate_lph >= 0 AND fuel_rate_lph <= 120",
             in_range("fuel_rate_lph", 0, 120)),
        Rule("fuel_level_range", "0 <= fuel_level_pct <= 100",
             "fuel_level_pct IS NOT NULL AND fuel_level_pct >= 0 AND fuel_level_pct <= 100",
             in_range("fuel_level_pct", 0, 100)),
        Rule("engine_load_range", "0 <= engine_load_pct <= 100",
             "engine_load_pct IS NOT NULL AND engine_load_pct >= 0 AND engine_load_pct <= 100",
             in_range("engine_load_pct", 0, 100)),
        Rule("engine_temp_range", "-20 <= engine_temp_c <= 180",
             "engine_temp_c IS NOT NULL AND engine_temp_c >= -20 AND engine_temp_c <= 180",
             in_range("engine_temp_c", -20, 180)),
        Rule("mileage_range", "mileage_km >= 0",
             "mileage_km IS NOT NULL AND mileage_km >= 0",
             lambda d: _num(d, "mileage_km") is not None and _num(d, "mileage_km") >= 0),
        Rule("weather_valid", "weather in {clear, rain, storm}",
             "weather IS NOT NULL AND weather IN ('clear', 'rain', 'storm')",
             lambda d: d.get("weather") in {"clear", "rain", "storm"}),
    ]


def _gps_rules() -> list[Rule]:
    def lat_ok(d):
        v = _num(d, "latitude")
        return v is not None and -90 <= v <= 90

    def lon_ok(d):
        v = _num(d, "longitude")
        return v is not None and -180 <= v <= 180

    def region_ok(d):
        return (_num(d, "latitude") is not None and _num(d, "longitude") is not None
                and 40 <= _num(d, "latitude") <= 50
                and -80 <= _num(d, "longitude") <= -60)

    return [
        Rule("event_id_present", "event_id is a non-empty string",
             "event_id IS NOT NULL AND event_id <> ''",
             lambda d: isinstance(d.get("event_id"), str) and bool(d["event_id"])),
        Rule("vehicle_id_pattern", "vehicle_id matches V#####",
             "vehicle_id IS NOT NULL AND vehicle_id RLIKE '^V\\\\d{5}$'",
             lambda d: isinstance(d.get("vehicle_id"), str)
             and bool(VEHICLE_ID_RE.match(d["vehicle_id"]))),
        Rule("timestamp_valid", "timestamp parses as ISO-8601",
             "timestamp IS NOT NULL",
             lambda d: _ts(d, "timestamp") is not None),
        Rule("latitude_range", "-90 <= latitude <= 90",
             "latitude IS NOT NULL AND latitude BETWEEN -90 AND 90", lat_ok),
        Rule("longitude_range", "-180 <= longitude <= 180",
             "longitude IS NOT NULL AND longitude BETWEEN -180 AND 180", lon_ok),
        Rule("gps_region", "coordinates inside the simulated region envelope",
             "latitude BETWEEN 40 AND 50 AND longitude BETWEEN -80 AND -60", region_ok),
        Rule("accuracy_range", "0 <= accuracy_m <= 1000",
             "accuracy_m IS NOT NULL AND accuracy_m >= 0 AND accuracy_m <= 1000",
             lambda d: _num(d, "accuracy_m") is not None
             and 0 <= _num(d, "accuracy_m") <= 1000),
    ]


def _delivery_rules() -> list[Rule]:
    return [
        Rule("delivery_id_pattern", "delivery_id matches DLV-######",
             "delivery_id IS NOT NULL AND delivery_id RLIKE '^DLV-\\\\d{6}$'",
             lambda d: isinstance(d.get("delivery_id"), str)
             and bool(DELIVERY_ID_RE.match(d["delivery_id"]))),
        Rule("route_id_pattern", "route_id matches R###",
             "route_id IS NOT NULL AND route_id RLIKE '^R\\\\d{3}$'",
             lambda d: isinstance(d.get("route_id"), str)
             and bool(ROUTE_ID_RE.match(d["route_id"]))),
        Rule("timestamp_valid", "timestamp parses as ISO-8601",
             "timestamp IS NOT NULL",
             lambda d: _ts(d, "timestamp") is not None),
        Rule("status_valid", "status in the four delivery statuses",
             "status IS NOT NULL AND status IN ('OUT_FOR_DELIVERY', 'DELIVERED', 'DELAYED', 'FAILED')",
             lambda d: d.get("status") in
             {"OUT_FOR_DELIVERY", "DELIVERED", "DELAYED", "FAILED"}),
        Rule("parcels_range", "0 <= parcels <= 10000",
             "parcels IS NOT NULL AND parcels >= 0 AND parcels <= 10000",
             lambda d: _num(d, "parcels") is not None
             and 0 <= _num(d, "parcels") <= 10000),
    ]


RULES_BY_TYPE: dict[str, list[Rule]] = {
    "telemetry": _telemetry_rules(),
    "gps": _gps_rules(),
    "delivery": _delivery_rules(),
}


def validate_record(event_type: str, record: dict) -> list[str]:
    """Return the names of all failing rules for one record ([] = valid)."""
    return [r.name for r in RULES_BY_TYPE[event_type] if not r.py(record)]


def rule_expressions(event_type: str) -> dict[str, str]:
    return {r.name: r.expr for r in RULES_BY_TYPE[event_type]}
