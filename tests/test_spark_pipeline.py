"""Tests for the Spark Structured Streaming transformation logic.

Runs with a local Spark session (marker: spark). Session-scoped so the JVM
starts once. NOTE: local Spark on Windows requires HADOOP_HOME pointing at
a winutils installation (see README); tests skip if Spark is unavailable.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.spark

pyspark = pytest.importorskip("pyspark")
from pyspark.sql import SparkSession  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from streaming.spark import aggregates, enrichment  # noqa: E402
from streaming.spark.streaming_job import normalize, with_validation  # noqa: E402
from streaming.spark.validation import validate_record  # noqa: E402

BASE_TS = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def spark():
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    session = (SparkSession.builder
               .master("local[2]")
               .appName("fleetiq-tests")
               .config("spark.ui.enabled", "false")
               .config("spark.sql.session.timeZone", "UTC")
               .config("spark.sql.shuffle.partitions", "4")
               .getOrCreate())
    yield session
    session.stop()


def _telemetry_rows(n: int = 6, route_id: str = "R001") -> list[dict]:
    rows = []
    for i in range(n):
        ts = BASE_TS + timedelta(seconds=10 * i)
        rows.append({
            "event_id": f"tele-{i:06d}",
            "vehicle_id": f"V{i % 2 + 1:05d}",
            "driver_id": f"D{i % 2 + 1:05d}",
            "route_id": route_id,
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "speed_kmh": 50.0 + i * 5.0,
            "fuel_rate_lph": 8.0 + i,
            "fuel_level_pct": 90.0 - i,
            "engine_load_pct": 40.0 + i,
            "engine_temp_c": 88.0,
            "ambient_temp_c": 20.0,
            "mileage_km": 1000.0 + i,
            "idle_time_s": 0.0,
            "dt_seconds": 10,
            "weather": "clear",
            "traffic_multiplier": 1.2,
            "event_type": "telemetry",
        })
    return rows


class TestValidationRules:
    def test_valid_telemetry_passes(self):
        rows = _telemetry_rows()
        for r in rows:
            assert validate_record("telemetry", r) == []

    def test_invalid_speed_detected(self):
        rows = _telemetry_rows()
        rows[0]["speed_kmh"] = 999.0
        assert "speed_range" in validate_record("telemetry", rows[0])

    def test_invalid_vehicle_id_detected(self):
        rows = _telemetry_rows()
        rows[0]["vehicle_id"] = "TRUCK-1"
        assert "vehicle_id_pattern" in validate_record("telemetry", rows[0])

    def test_missing_timestamp_detected(self):
        rows = _telemetry_rows()
        del rows[0]["timestamp"]
        assert "timestamp_valid" in validate_record("telemetry", rows[0])

    def test_bad_gps_region_detected(self):
        gps = {"event_id": "gps-1", "vehicle_id": "V00001", "route_id": "R001",
               "timestamp": BASE_TS.isoformat().replace("+00:00", "Z"),
               "latitude": 0.0, "longitude": 0.0, "accuracy_m": 5.0,
               "event_type": "gps"}
        errors = validate_record("gps", gps)
        assert "gps_region" in errors

    def test_bad_delivery_status_detected(self):
        d = {"event_id": "del-1", "delivery_id": "DLV-000001", "route_id": "R001",
             "stop_index": 0, "timestamp": BASE_TS.isoformat().replace("+00:00", "Z"),
             "status": "LOST_IN_TRANSIT", "planned_arrival_time": None,
             "parcels": 5, "weather": "clear", "event_type": "delivery"}
        assert "status_valid" in validate_record("delivery", d)


class TestSparkValidation:
    def test_with_validation_splits_rows(self, spark):
        rows = _telemetry_rows()
        rows[0]["speed_kmh"] = -5.0  # invalid
        df = spark.createDataFrame(rows)
        validated = with_validation(df, "telemetry")
        errors = validated.filter(F.size("validation_errors") > 0)
        assert errors.count() == 1
        assert "speed_range" in errors.select(F.explode("validation_errors")).first()[0]

    def test_normalize_casts_timestamps(self, spark):
        rows = _telemetry_rows()
        df = spark.createDataFrame(rows)  # timestamps as strings
        out = normalize(df, "telemetry")
        assert dict(out.dtypes)["timestamp"] == "timestamp"


class TestEnrichment:
    def test_fuel_per_100km(self, spark):
        rows = _telemetry_rows()
        df = spark.createDataFrame(rows)
        out = enrichment.enrich_telemetry(df)
        sample = out.orderBy("event_id").first()
        assert sample["fuel_per_100km"] is not None

    def test_haversine_known_distance(self):
        # Paris ~ 2.35 km for 0.02 deg lat; just check sanity bounds
        d = enrichment.haversine_km(45.42, -73.62, 45.45, -73.60)
        assert 2.0 < d < 5.0


class TestAggregates:
    def test_fleet_kpis_window(self, spark):
        rows = _telemetry_rows(6)
        df = spark.createDataFrame(rows)
        agg = aggregates.fleet_kpis(df)
        assert agg.count() == 1  # all rows in one 5-min window
        row = agg.first()
        assert row["active_vehicles"] == 2
        assert row["avg_speed_kmh"] > 0
        assert row["total_distance_km"] > 0

    def test_vehicle_health_attention_flag(self, spark):
        rows = _telemetry_rows(6)
        rows[2]["engine_temp_c"] = 120.0
        df = spark.createDataFrame(rows)
        agg = aggregates.vehicle_health(df)
        flagged = agg.filter(F.col("attention_flag") == "temp_alert")
        assert flagged.count() == 1

    def test_route_performance_filters_null_routes(self, spark):
        rows = _telemetry_rows(4)
        rows[0]["route_id"] = None
        df = spark.createDataFrame(rows)
        agg = aggregates.route_performance(df)
        assert agg.count() == 1
        assert agg.first()["route_id"] == "R001"

    def test_delivery_performance_counts(self, spark):
        rows = [
            {"event_id": f"del-{i}", "delivery_id": f"DLV-00000{i}",
             "vehicle_id": "V00001", "route_id": "R001", "stop_index": i,
             "timestamp": (BASE_TS + timedelta(minutes=10 * i)).isoformat(),
             "status": s,
             "planned_arrival_time": (BASE_TS + timedelta(minutes=10 * i)).isoformat(),
             "parcels": 3, "weather": "clear", "event_type": "delivery"}
            for i, s in enumerate(["DELIVERED", "DELAYED", "FAILED", "DELIVERED"])
        ]
        df = spark.createDataFrame(rows)
        agg = aggregates.delivery_performance(df)
        row = agg.first()
        assert row["completed_deliveries"] == 4
        assert row["on_time"] == 2
        assert row["delayed"] == 1
        assert row["failed"] == 1
        assert abs(row["on_time_rate"] - 0.5) < 1e-9

