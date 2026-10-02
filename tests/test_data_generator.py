"""Tests for the synthetic data generator.

Covers: population factories, determinism/reproducibility, correlations
(traffic->speed, idle->fuel, age->anomaly risk), event schemas, trip
lifecycle and the CLI.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from data_generator.cli import build_parser, main, write_simulation_output
from data_generator.models import GeoPoint, VehicleType
from data_generator.simulation import (
    FleetSimulator,
    make_deliveries,
    make_hubs,
    make_routes,
    make_vehicles,
)


@pytest.fixture(scope="module")
def population():
    hubs = make_hubs(42)
    vehicles, drivers = make_vehicles(42, 30)
    routes = make_routes(42, hubs, count=8)
    deliveries = make_deliveries(42, routes, per_route=6)
    return hubs, vehicles, drivers, routes, deliveries


# --------------------------------------------------------------------------
# Population factories
# --------------------------------------------------------------------------
class TestFactories:
    def test_hubs_are_unique_and_within_region(self, population):
        hubs, *_ = population
        ids = [h.hub_id for h in hubs]
        assert len(ids) == len(set(ids)) == 25
        for h in hubs:
            assert -90 <= h.location.latitude <= 90
            assert -180 <= h.location.longitude <= 180

    def test_make_vehicles_count_and_ids(self, population):
        _, vehicles, drivers, *_ = population
        assert len(vehicles) == 30
        assert len(drivers) == 30
        assert len({v.vehicle_id for v in vehicles}) == 30
        for d in drivers:
            assert d.vehicle_id in {v.vehicle_id for v in vehicles}

    def test_vehicle_types_valid(self, population):
        _, vehicles, *_ = population
        assert all(v.vehicle_type in VehicleType for v in vehicles)

    def test_vehicle_age_correlates_with_anomaly_risk(self, population):
        _, vehicles, *_ = population
        ages = [v.age_years for v in vehicles]
        risks = [v.anomaly_risk for v in vehicles]
        # risk = min(0.9, base * (1 + 0.35*age)) -> positive association
        corr = pd.Series(ages).corr(pd.Series(risks), method="spearman")
        assert corr > 0.3

    def test_routes_have_valid_geometry(self, population):
        *_, routes, _ = population
        assert len(routes) == 8
        for r in routes:
            assert r.origin_hub_id != r.destination_hub_id
            assert r.distance_km > 1.0
            assert 0.5 <= r.congestion_factor <= 2.5
            assert r.typical_duration_min > 0
            assert len(r.waypoints) >= 3

    def test_deliveries_have_unique_ids(self, population):
        *_, deliveries = population
        assert len({d.delivery_id for d in deliveries}) == len(deliveries)
        assert all(0.15 <= d.stop_fraction <= 0.98 for d in deliveries)

    def test_geo_distance_symmetry(self):
        a = GeoPoint(45.42, -73.62)
        b = GeoPoint(45.45, -73.60)
        assert abs(a.distance_km(b) - b.distance_km(a)) < 1e-9
        assert 0 < a.distance_km(b) < 10


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
class TestReproducibility:
    def test_same_seed_same_events(self, population):
        hubs, vehicles, drivers, routes, _ = population
        start = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
        sim1 = FleetSimulator(vehicles, drivers, hubs, routes,
                              make_deliveries(42, routes, per_route=6),
                              seed=42, start_time=start, sim_days=1, dt_seconds=60)
        sim2 = FleetSimulator(vehicles, drivers, hubs, routes,
                              make_deliveries(42, routes, per_route=6),
                              seed=42, start_time=start, sim_days=1, dt_seconds=60)
        e1 = list(sim1.run(max_events=500))
        e2 = list(sim2.run(max_events=500))
        assert len(e1) == len(e2) == 500
        assert [e["event_id"] for e in e1] == [e["event_id"] for e in e2]

    def test_different_seed_different_events(self, population):
        hubs, vehicles, drivers, routes, _ = population
        start = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
        sim1 = FleetSimulator(vehicles, drivers, hubs, routes,
                              make_deliveries(1, routes, per_route=6),
                              seed=1, start_time=start, sim_days=1, dt_seconds=60)
        sim2 = FleetSimulator(vehicles, drivers, hubs, routes,
                              make_deliveries(2, routes, per_route=6),
                              seed=2, start_time=start, sim_days=1, dt_seconds=60)
        e1 = list(sim1.run(max_events=300))
        e2 = list(sim2.run(max_events=300))
        assert [e["event_id"] for e in e1] != [e["event_id"] for e in e2]


# --------------------------------------------------------------------------
# Event content
# --------------------------------------------------------------------------
class TestEvents:
    @pytest.fixture()
    def events(self, population):
        hubs, vehicles, drivers, routes, _ = population
        sim = FleetSimulator(vehicles, drivers, hubs, routes,
                             make_deliveries(42, routes, per_route=6),
                             seed=42,
                             start_time=datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc),
                             sim_days=1, dt_seconds=60)
        return list(sim.run(max_events=1500))

    def test_event_types_present(self, events):
        types = {e["event_type"] for e in events}
        assert {"telemetry", "gps"} <= types

    def test_telemetry_fields_ranges(self, events):
        teles = [e for e in events if e["event_type"] == "telemetry"]
        assert teles
        for e in teles:
            assert 0 <= e["speed_kmh"] <= 200
            assert 0 <= e["fuel_rate_lph"] <= 120
            assert 0 <= e["fuel_level_pct"] <= 100
            assert 0 <= e["engine_load_pct"] <= 100
            assert -20 <= e["engine_temp_c"] <= 180
            assert e["mileage_km"] >= 0
            assert e["idle_time_s"] >= 0
            assert e["weather"] in {"clear", "rain", "storm"}
            assert e["vehicle_id"].startswith("V")

    def test_gps_coordinates_near_region(self, events):
        gps = [e for e in events if e["event_type"] == "gps"]
        assert gps
        for e in gps:
            assert 44.0 < e["latitude"] < 47.0
            assert -76.0 < e["longitude"] < -71.0

    def test_correlated_traffic_speed(self, events):
        """High traffic multiplier must correlate with lower speed."""
        teles = [e for e in events if e["event_type"] == "telemetry" and e["speed_kmh"] > 5]
        low_traffic = [e for e in teles if e["traffic_multiplier"] < 1.2]
        high_traffic = [e for e in teles if e["traffic_multiplier"] > 1.6]
        if not high_traffic:
            pytest.skip("no high-traffic samples in this run")
        assert pd.Series([e["speed_kmh"] for e in high_traffic]).mean() < \
            pd.Series([e["speed_kmh"] for e in low_traffic]).mean()

    def test_idle_burns_fuel(self, events):
        """Idling events must show positive fuel rate even at zero speed."""
        idling = [e for e in events if e["event_type"] == "telemetry"
                  and e["idle_time_s"] > 0 and e["speed_kmh"] == 0]
        assert any(e["fuel_rate_lph"] > 0 for e in idling)


    def test_delivery_events_emitted(self, population):
        hubs, vehicles, drivers, routes, _ = population
        sim = FleetSimulator(vehicles, drivers, hubs, routes,
                             make_deliveries(42, routes, per_route=6),
                             seed=9,
                             start_time=datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc),
                             sim_days=1, dt_seconds=30)
        all_events = list(sim.run(max_events=6000))
        deliveries = [e for e in all_events if e["event_type"] == "delivery"]
        assert deliveries, "expected delivery events"
        statuses = {e["status"] for e in deliveries}
        assert "OUT_FOR_DELIVERY" in statuses
        assert statuses & {"DELIVERED", "DELAYED", "FAILED"}
        for e in deliveries:
            assert e["delivery_id"].startswith("DLV-")
            assert e["route_id"].startswith("R")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
class TestCLI:
    def test_parser_defaults(self):
        args = build_parser().parse_args([])
        assert args.vehicles == 500
        assert args.seed == 42
        assert args.speed == 50

    def test_parser_flags(self):
        args = build_parser().parse_args(
            ["--vehicles", "10", "--events", "0", "--speed", "25", "--seed", "3"])
        assert args.vehicles == 10
        assert args.events == 0
        assert args.speed == 25
        assert args.seed == 3

    def test_cli_writes_parquet(self, tmp_path):
        out = tmp_path / "raw"
        rc = main(["--vehicles", "10", "--events", "4000", "--days", "1",
                   "--routes", "6", "--deliveries-per-route", "6",
                   "--output-dir", str(out), "--seed", "11"])
        assert rc == 0
        for name in ("vehicles", "drivers", "routes", "hubs", "telemetry", "gps"):
            assert (out / f"{name}.parquet").exists()
        md = json.loads((out / "metadata.json").read_text())
        assert md["counts"]["vehicles"] == 10
        assert md["events_total"] > 0
        vehicles = pd.read_parquet(out / "vehicles.parquet")
        assert len(vehicles) == 10

    def test_cli_reproducible_across_runs(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        common = ["--vehicles", "8", "--events", "3000", "--days", "1",
                  "--routes", "5", "--deliveries-per-route", "4", "--seed", "5"]
        assert main(common + ["--output-dir", str(a)]) == 0
        assert main(common + ["--output-dir", str(b)]) == 0
        ta = pd.read_parquet(a / "telemetry.parquet")
        tb = pd.read_parquet(b / "telemetry.parquet")
        assert ta.equals(tb)

    def test_cli_invalid_vehicle_count(self, tmp_path):
        rc = main(["--vehicles", "0", "--events", "100",
                   "--output-dir", str(tmp_path / "empty"), "--seed", "1"])
        assert rc == 0  # empty fleet is a valid (degenerate) configuration


def test_write_simulation_output(tmp_path, population):
    hubs, vehicles, drivers, routes, deliveries = population
    stats = write_simulation_output(tmp_path, vehicles, drivers, hubs, routes,
                                    deliveries, [], [])
    assert stats["vehicles"] == 30
    assert (tmp_path / "routes.parquet").exists()

