"""Tests for the Pandera data-quality schemas + report generation."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from data_quality.report import run_report, validate_dataframe
from data_quality.schemas import schema_for

BASE_TS = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc).isoformat()


def _telemetry_df(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame([{
        "event_id": f"tele-{i:06d}",
        "vehicle_id": f"V{i % 2 + 1:05d}",
        "driver_id": f"D{i % 2 + 1:05d}",
        "route_id": "R001",
        "timestamp": BASE_TS,
        "speed_kmh": 55.0,
        "fuel_rate_lph": 8.0,
        "fuel_level_pct": 80.0,
        "engine_load_pct": 40.0,
        "engine_temp_c": 88.0,
        "ambient_temp_c": 20.0,
        "mileage_km": 1000.0,
        "idle_time_s": 0.0,
        "dt_seconds": 10,
        "weather": "clear",
        "traffic_multiplier": 1.0,
        "event_type": "telemetry",
    } for i in range(n)])


class TestPanderaSchemas:
    def test_schema_for_known_types(self):
        assert schema_for("telemetry").__name__ == "TelemetrySchema"
        assert schema_for("gps").__name__ == "GpsSchema"
        assert schema_for("delivery").__name__ == "DeliverySchema"

    def test_schema_for_unknown_raises(self):
        with pytest.raises(ValueError):
            schema_for("unknown")

    def test_valid_telemetry_passes(self):
        result = validate_dataframe(_telemetry_df(), "telemetry")
        assert result["valid"] is True
        assert result["n_invalid"] == 0

    def test_speed_range_violation_caught(self):
        df = _telemetry_df()
        df.loc[0, "speed_kmh"] = -10.0
        result = validate_dataframe(df, "telemetry")
        assert result["valid"] is False
        assert result["n_invalid"] == 1
        assert any("speed_kmh" in e["column"] for e in result["errors"])

    def test_vehicle_id_pattern_caught(self):
        df = _telemetry_df()
        df.loc[0, "vehicle_id"] = "BAD-ID"
        result = validate_dataframe(df, "telemetry")
        assert result["valid"] is False
        assert any("vehicle_id" in e["column"] for e in result["errors"])

    def test_missing_column_rejected(self):
        df = _telemetry_df().drop(columns=["fuel_rate_lph"])
        result = validate_dataframe(df, "telemetry")
        assert result["valid"] is False

    def test_gps_latitude_bounds(self):
        gps = pd.DataFrame([{
            "event_id": "gps-1", "vehicle_id": "V00001", "route_id": "R001",
            "timestamp": BASE_TS, "latitude": 95.0, "longitude": -73.62,
            "accuracy_m": 5.0, "event_type": "gps",
        }])
        result = validate_dataframe(gps, "gps")
        assert result["valid"] is False

    def test_delivery_status_enum(self):
        deliv = pd.DataFrame([{
            "delivery_id": "DLV-000001", "route_id": "R001", "vehicle_id": "V00001",
            "stop_index": 0, "timestamp": BASE_TS, "status": "NOPE",
            "planned_arrival_time": None, "parcels": 2, "weather": "clear",
            "event_type": "delivery",
        }])
        result = validate_dataframe(deliv, "delivery")
        assert result["valid"] is False


class TestReport:
    def test_run_report_writes_json_and_parquet(self, tmp_path):
        df = _telemetry_df()
        df.loc[0, "speed_kmh"] = 999.0
        src = tmp_path / "telemetry.parquet"
        df.to_parquet(src, index=False)
        out = tmp_path / "reports"
        report = run_report(src, "telemetry", out)
        assert report["total_records"] == 5
        assert report["invalid_records"] == 1
        assert (out / "quality_telemetry.json").exists()
        assert (out / "invalid_telemetry.parquet").exists()
        invalid = pd.read_parquet(out / "invalid_telemetry.parquet")
        assert len(invalid) == 1

    def test_run_report_all_valid(self, tmp_path):
        df = _telemetry_df()
        src = tmp_path / "telemetry.parquet"
        df.to_parquet(src, index=False)
        report = run_report(src, "telemetry", tmp_path / "reports")
        assert report["invalid_records"] == 0
        assert report["validity_rate"] == 1.0
