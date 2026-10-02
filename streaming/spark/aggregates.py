"""Gold-layer windowed aggregations (5-minute tumbling windows, event time).

All aggregates use ``window(timestamp, '5 minutes')`` with a 10-minute
watermark on the event-time column. Aggregate names match the gold table
schemas documented in docs/data-lake.md.

Distance approximation (documented): per-event distance is approximated as
``speed_kmh * dt_seconds / 3600`` (the generator reports its tick interval
in ``dt_seconds``). Exact path distance from consecutive GPS fixes is
computed in the batch feature pipeline (ml/features.py).
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

WINDOW_DURATION = "5 minutes"
WATERMARK_DURATION = "10 minutes"


def _windowed(df: DataFrame) -> DataFrame:
    return df.withWatermark("timestamp", WATERMARK_DURATION)


# ---------------------------------------------------------------------------
# Fleet KPIs (global, per 5-min window)
# ---------------------------------------------------------------------------
def fleet_kpis(telemetry: DataFrame) -> DataFrame:
    return (
        _windowed(telemetry)
        .groupBy(F.window("timestamp", WINDOW_DURATION))
        .agg(
            # approx_count_distinct: exact distinct is unsupported in streaming
            F.approx_count_distinct("vehicle_id", rsd=0.02).alias("active_vehicles"),
            F.avg("speed_kmh").alias("avg_speed_kmh"),
            F.avg("fuel_rate_lph").alias("avg_fuel_rate_lph"),
            F.sum(F.col("speed_kmh") * F.col("dt_seconds") / 3600.0).alias("total_distance_km"),
            F.sum("idle_time_s").alias("total_idle_s"),
            F.count("*").alias("telemetry_events"),
        )
    )


# ---------------------------------------------------------------------------
# Route performance (per window + route)
# ---------------------------------------------------------------------------
def route_performance(telemetry: DataFrame) -> DataFrame:
    return (
        _windowed(telemetry)
        .filter(F.col("route_id").isNotNull())
        .groupBy(F.window("timestamp", WINDOW_DURATION), "route_id")
        .agg(
            F.approx_count_distinct("vehicle_id", rsd=0.02).alias("vehicles_on_route"),
            F.avg("speed_kmh").alias("avg_speed_kmh"),
            F.avg("traffic_multiplier").alias("avg_traffic_multiplier"),
            F.avg("fuel_per_100km").alias("avg_fuel_per_100km"),
            F.sum(F.col("speed_kmh") * F.col("dt_seconds") / 3600.0).alias("total_distance_km"),
            F.sum("idle_time_s").alias("total_idle_s"),
            F.count("*").alias("telemetry_events"),
        )
    )


# ---------------------------------------------------------------------------
# Vehicle health (per window + vehicle)
# ---------------------------------------------------------------------------
def vehicle_health(telemetry: DataFrame) -> DataFrame:
    return (
        _windowed(telemetry)
        .groupBy(F.window("timestamp", WINDOW_DURATION), "vehicle_id")
        .agg(
            F.avg("speed_kmh").alias("avg_speed_kmh"),
            F.max("speed_kmh").alias("max_speed_kmh"),
            F.stddev("speed_kmh").alias("speed_stddev_kmh"),
            F.avg("engine_load_pct").alias("avg_engine_load_pct"),
            F.max("engine_temp_c").alias("max_engine_temp_c"),
            F.sum("idle_time_s").alias("total_idle_s"),
            F.sum(F.col("fuel_rate_lph") * F.col("dt_seconds") / 3600.0).alias("fuel_l"),
            F.count("*").alias("telemetry_events"),
        )
        .withColumn(
            "attention_flag",
            F.when(F.col("max_engine_temp_c") > 112.0, "temp_alert")
            .when(F.col("avg_engine_load_pct") > 92.0, "engine_load_alert")
            .when(
                (F.col("total_idle_s") / F.col("telemetry_events") / 10.0) > 0.6,
                "excess_idle",
            )
            .otherwise("ok"),
        )
    )


# ---------------------------------------------------------------------------
# Delivery performance (per window + route)
# ---------------------------------------------------------------------------
def delivery_performance(deliveries: DataFrame) -> DataFrame:
    terminal = deliveries.filter(F.col("status").isin("DELIVERED", "DELAYED", "FAILED"))
    return (
        _windowed(terminal)
        .withColumn(
            "delay_minutes",
            F.when(
                F.col("planned_arrival_time").isNotNull(),
                (F.unix_timestamp("timestamp") - F.unix_timestamp("planned_arrival_time")) / 60.0,
            ).otherwise(None),
        )
        .groupBy(F.window("timestamp", WINDOW_DURATION), "route_id")
        .agg(
            F.count("*").alias("completed_deliveries"),
            F.sum(F.when(F.col("status") == "DELIVERED", 1).otherwise(0)).alias("on_time"),
            F.sum(F.when(F.col("status") == "DELAYED", 1).otherwise(0)).alias("delayed"),
            F.sum(F.when(F.col("status") == "FAILED", 1).otherwise(0)).alias("failed"),
            F.avg("delay_minutes").alias("avg_delay_minutes"),
        )
        .withColumn(
            "on_time_rate",
            F.when(F.col("completed_deliveries") > 0,
                   F.col("on_time") / F.col("completed_deliveries"))
            .otherwise(None),
        )
    )
