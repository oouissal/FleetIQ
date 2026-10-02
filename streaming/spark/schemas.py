"""Spark StructType schemas mirroring the Kafka JSON schemas 1:1."""

from __future__ import annotations

from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

TELEMETRY_SCHEMA = StructType([
    StructField("event_id", StringType(), False),
    StructField("vehicle_id", StringType(), False),
    StructField("driver_id", StringType(), True),
    StructField("route_id", StringType(), True),
    StructField("timestamp", TimestampType(), False),
    StructField("speed_kmh", DoubleType(), True),
    StructField("fuel_rate_lph", DoubleType(), True),
    StructField("fuel_level_pct", DoubleType(), True),
    StructField("engine_load_pct", DoubleType(), True),
    StructField("engine_temp_c", DoubleType(), True),
    StructField("ambient_temp_c", DoubleType(), True),
    StructField("mileage_km", DoubleType(), True),
    StructField("idle_time_s", DoubleType(), True),
    StructField("dt_seconds", LongType(), True),
    StructField("weather", StringType(), True),
    StructField("traffic_multiplier", DoubleType(), True),
    StructField("event_type", StringType(), True),
])

GPS_SCHEMA = StructType([
    StructField("event_id", StringType(), False),
    StructField("vehicle_id", StringType(), False),
    StructField("route_id", StringType(), True),
    StructField("timestamp", TimestampType(), False),
    StructField("latitude", DoubleType(), True),
    StructField("longitude", DoubleType(), True),
    StructField("accuracy_m", DoubleType(), True),
    StructField("event_type", StringType(), True),
])

DELIVERY_SCHEMA = StructType([
    StructField("event_id", StringType(), False),
    StructField("delivery_id", StringType(), False),
    StructField("vehicle_id", StringType(), True),
    StructField("route_id", StringType(), True),
    StructField("stop_index", IntegerType(), True),
    StructField("timestamp", TimestampType(), False),
    StructField("status", StringType(), True),
    StructField("planned_arrival_time", TimestampType(), True),
    StructField("parcels", IntegerType(), True),
    StructField("weather", StringType(), True),
    StructField("event_type", StringType(), True),
])

SCHEMAS_BY_TYPE = {
    "telemetry": TELEMETRY_SCHEMA,
    "gps": GPS_SCHEMA,
    "delivery": DELIVERY_SCHEMA,
}


def schema_for(event_type: str) -> StructType:
    if event_type not in SCHEMAS_BY_TYPE:
        raise ValueError(f"Unknown event type: {event_type!r}")
    return SCHEMAS_BY_TYPE[event_type]
