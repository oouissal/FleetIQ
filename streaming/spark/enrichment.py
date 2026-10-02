"""Enrichment logic for the silver layer.

Pure Python helpers are unit-testable; Spark transforms wrap them.

Streaming enrichments (row-wise only):
telemetry:
  * fuel_per_100km — fuel_rate_lph * 100 / speed (only when speed > 5).

Known limitation (documented in docs/data-lake.md): Spark Structured
Streaming rejects non-time-windowed LAG over streaming DataFrames, so
acceleration and GPS point-to-point distance are computed in the BATCH
feature pipeline (ml/features.py) instead of the streaming one. The pure
helpers (haversine_km, speed_between_kmh) remain here for that path.
"""

from __future__ import annotations

import math
from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[float]:
    """Great-circle distance in km between two coordinates."""
    if any(v is None for v in (lat1, lon1, lat2, lon2)):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def speed_between_kmh(distance_km: Optional[float], dt_seconds: Optional[float]) -> Optional[float]:
    if distance_km is None or dt_seconds is None or dt_seconds <= 0:
        return None
    return min(200.0, distance_km / (dt_seconds / 3600.0))


def fuel_per_100km(fuel_rate_lph: Optional[float], speed_kmh: Optional[float]) -> Optional[float]:
    if fuel_rate_lph is None or speed_kmh is None or speed_kmh <= 5.0:
        return None  # meaningless at crawling speed; documented
    return fuel_rate_lph * 100.0 / speed_kmh


# ---------------------------------------------------------------------------
# Spark transforms (row-wise only)
# ---------------------------------------------------------------------------
def enrich_telemetry(df: DataFrame, watermark: str = "10 minutes") -> DataFrame:
    """Streaming enrichment (row-wise only, no stateful window functions).

    fuel_per_100km is added here; acceleration is computed in the batch
    feature pipeline (ml/features.py) because Spark Structured Streaming
    rejects non-time-windowed LAG over streaming DataFrames. This is a
    documented simplification, not silent data loss.
    """
    from pyspark.sql.types import DoubleType

    fuel100 = F.udf(fuel_per_100km, DoubleType())
    return df.withColumn("fuel_per_100km", fuel100("fuel_rate_lph", "speed_kmh"))


def enrich_gps(df: DataFrame, watermark: str = "10 minutes") -> DataFrame:
    """Streaming GPS "enrichment": no stateful ops (see module docstring).

    Point-to-point distance/speed between consecutive fixes are computed in
    the batch feature pipeline instead.
    """
    return df
