"""Tests for Kafka schemas, topic routing, config and producer logic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from streaming.kafka import schemas as kschemas
from streaming.kafka.config import KafkaConfig
from streaming.kafka.producer import FleetEventProducer, ensure_topics

BASE_TS = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)


def valid_telemetry() -> dict:
    return {
        "event_id": "tele-000000000001",
        "vehicle_id": "V00001",
        "driver_id": "D00001",
        "route_id": "R001",
        "timestamp": BASE_TS,
        "speed_kmh": 60.0,
        "fuel_rate_lph": 8.5,
        "fuel_level_pct": 80.0,
        "engine_load_pct": 45.0,
        "engine_temp_c": 88.0,
        "ambient_temp_c": 20.0,
        "mileage_km": 1000.0,
        "idle_time_s": 0.0,
        "dt_seconds": 10,
        "weather": "clear",
        "traffic_multiplier": 1.1,
        "event_type": "telemetry",
    }


def valid_gps() -> dict:
    return {
        "event_id": "gps-000000000001",
        "vehicle_id": "V00001",
        "route_id": "R001",
        "timestamp": BASE_TS,
        "latitude": 45.42,
        "longitude": -73.62,
        "accuracy_m": 5.0,
        "event_type": "gps",
    }


def valid_delivery() -> dict:
    return {
        "event_id": "del-000000000001",
        "delivery_id": "DLV-000001",
        "vehicle_id": "V00001",
        "route_id": "R001",
        "stop_index": 2,
        "timestamp": BASE_TS,
        "status": "DELIVERED",
        "planned_arrival_time": BASE_TS,
        "parcels": 5,
        "weather": "clear",
        "event_type": "delivery",
    }


class TestSchemas:
    def test_valid_telemetry_accepted(self):
        kschemas.validate_event(valid_telemetry())

    def test_valid_gps_accepted(self):
        kschemas.validate_event(valid_gps())

    def test_valid_delivery_accepted(self):
        kschemas.validate_event(valid_delivery())

    def test_invalid_event_type_rejected(self):
        ev = valid_telemetry()
        ev["event_type"] = "telemetry_x"
        with pytest.raises((ValidationError, ValueError)):
            kschemas.validate_event(ev)

    @pytest.mark.parametrize("field,value", [
        ("vehicle_id", "T1"),
        ("speed_kmh", -1),
        ("speed_kmh", 300),
        ("fuel_level_pct", 150),
        ("engine_load_pct", -5),
        ("weather", "snow"),
    ])
    def test_invalid_telemetry_rejected(self, field, value):
        ev = valid_telemetry()
        ev[field] = value
        with pytest.raises(ValidationError):
            kschemas.validate_event(ev)

    def test_invalid_gps_coordinates_rejected(self):
        ev = valid_gps()
        ev["latitude"] = 999
        with pytest.raises(ValidationError):
            kschemas.validate_event(ev)

    def test_invalid_delivery_status_rejected(self):
        ev = valid_delivery()
        ev["status"] = "LOST"
        with pytest.raises(ValidationError):
            kschemas.validate_event(ev)

    def test_null_planned_arrival_ok(self):
        ev = valid_delivery()
        ev["planned_arrival_time"] = None
        kschemas.validate_event(ev)


class TestRouting:
    def test_topic_mapping(self):
        assert kschemas.topic_for_event(valid_telemetry()) == "fleet.telemetry"
        assert kschemas.topic_for_event(valid_gps()) == "fleet.gps"
        assert kschemas.topic_for_event(valid_delivery()) == "fleet.delivery"

    def test_unknown_event_type_raises(self):
        with pytest.raises(ValueError):
            kschemas.topic_for_event({"event_type": "mystery"})

    def test_schema_for_event_type(self):
        assert kschemas.schema_for_event_type("telemetry") is kschemas.TelemetryEvent
        assert kschemas.schema_for_event_type("gps") is kschemas.GpsEvent
        assert kschemas.schema_for_event_type("delivery") is kschemas.DeliveryEvent
        with pytest.raises(ValueError):
            kschemas.schema_for_event_type("nope")


class TestConfig:
    def test_defaults(self):
        cfg = KafkaConfig()
        assert cfg.bootstrap_servers == "localhost:9092"
        assert cfg.topics == ["fleet.telemetry", "fleet.gps", "fleet.delivery"]

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:9093")
        monkeypatch.setenv("KAFKA_TOPIC_TELEMETRY", "fleet.telemetry.custom")
        cfg = KafkaConfig()
        assert cfg.bootstrap_servers == "broker:9093"
        assert cfg.topic_telemetry == "fleet.telemetry.custom"


class TestProducer:
    def test_producer_rejects_invalid_without_broker(self):
        """Validation happens before any network call, so constructing the
        producer must not require a broker."""
        producer = FleetEventProducer(bootstrap_servers="localhost:1")
        with pytest.raises(ValidationError):
            producer.send({"event_type": "telemetry", "speed_kmh": "fast"})

    def test_ensure_topics_no_broker_is_safe(self):
        """ensure_topics must not raise when no broker is reachable."""
        ensure_topics("localhost:1", ["fleet.telemetry"])  # logs a warning
