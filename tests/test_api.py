"""FastAPI endpoint tests against a real tiny dataset + trained models.

Creates a full local environment once per session:
    generator -> gold tables -> ETA + anomaly models (MLflow file store)
then exercises every endpoint through the TestClient.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    root = tmp_path_factory.mktemp("api_env")
    raw = root / "raw"
    gold = root / "gold"
    meta = root / "ml_meta"
    mlruns = root / "mlruns"
    gold.mkdir()

    from data_generator.cli import main as gen_main

    rc = gen_main(["--vehicles", "10", "--events", "15000", "--days", "2",
                   "--routes", "8", "--deliveries-per-route", "30",
                   "--output-dir", str(raw), "--seed", "33"])
    assert rc == 0

    from ml.gold import build_all

    build_all(raw, gold)

    from ml.train_anomaly import train as train_anomaly
    from ml.train_eta import train as train_eta

    train_anomaly(raw, gold, tracking_uri=str(mlruns))
    train_eta(raw, tracking_uri=str(mlruns),
              results_file=meta / "eta_results.json")

    os.environ.update({
        "FLEETIQ_RAW_ROOT": str(raw),
        "FLEETIQ_GOLD_ROOT": str(gold),
        "FLEETIQ_LAKE_BASE": "",
        "FLEETIQ_RESULTS_META_DIR": str(meta),
        "FLEETIQ_ANOMALY_META_DIR": str(gold),
        "FLEETIQ_MLFLOW_TRACKING_URI": str(mlruns),
    })

    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    yield client


class TestHealth:
    def test_health_ok(self, api_env):
        client = api_env
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["data_available"] is True
        assert body["models_available"] is True


class TestKpis:
    def test_kpis(self, api_env):
        client = api_env
        r = client.get("/api/kpis")
        assert r.status_code == 200
        body = r.json()
        assert body["active_vehicles"] >= 0
        assert body["total_deliveries"] >= 0
        assert "note" in body

    def test_kpi_series(self, api_env):
        client = api_env
        r = client.get("/api/kpis/series")
        assert r.status_code == 200
        series = r.json()["series"]
        assert len(series) > 0
        assert "active_vehicles" in series[0]


class TestFleet:
    def test_summary(self, api_env):
        client = api_env
        r = client.get("/api/fleet/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["vehicles_total"] == 10
        assert "vehicle_types" in body

    def test_vehicles_list(self, api_env):
        client = api_env
        r = client.get("/api/fleet/vehicles", params={"limit": 5})
        assert r.status_code == 200
        assert len(r.json()) == 5

    def test_vehicles_search_and_sort(self, api_env):
        client = api_env
        r = client.get("/api/fleet/vehicles",
                       params={"search": "V000", "sort_by": "vehicle_id",
                               "order": "desc", "limit": 3})
        assert r.status_code == 200
        ids = [v["vehicle_id"] for v in r.json()]
        assert ids == sorted(ids, reverse=True)

    def test_vehicle_detail(self, api_env):
        client = api_env
        r = client.get("/api/fleet/vehicles/V00001")
        assert r.status_code == 200
        body = r.json()
        assert body["vehicle_id"] == "V00001"
        assert "current" in body
        assert "history_speed" in body

    def test_vehicle_detail_404(self, api_env):
        client = api_env
        assert client.get("/api/fleet/vehicles/V99999").status_code == 404


class TestAnalytics:
    def test_routes(self, api_env):
        client = api_env
        r = client.get("/api/routes")
        assert r.status_code == 200
        assert len(r.json()["routes"]) > 0

    def test_deliveries(self, api_env):
        client = api_env
        r = client.get("/api/deliveries", params={"limit": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] > 0
        assert len(body["deliveries"]) <= 10

    def test_deliveries_filter_status(self, api_env):
        client = api_env
        r = client.get("/api/deliveries", params={"status": "DELIVERED"})
        assert r.status_code == 200
        assert all(d["status"] == "DELIVERED" for d in r.json()["deliveries"])


class TestAnomaliesEndpoint:
    def test_anomalies_list(self, api_env):
        client = api_env
        r = client.get("/api/anomalies", params={"limit": 20})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] > 0
        assert all("pattern" in a for a in body["anomalies"])


class TestModels:
    def test_model_info(self, api_env):
        client = api_env
        r = client.get("/api/model/info")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["eta_model"]["metrics"]["mae"] > 0
        assert body["anomaly_model"]["method"] == "IsolationForest (unsupervised)"

    def test_predict_eta(self, api_env):
        client = api_env
        payload = {"distance_km": 40, "vehicle_type": "BOX_TRUCK",
                   "weather": "clear", "parcels": 10}
        r = client.post("/api/predict/eta", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["predicted_eta_minutes"] > 0
        assert body["interval"]["lower_minutes"] <= body["interval"]["upper_minutes"]
        assert body["model_version"] is not None

    def test_predict_eta_invalid_payload(self, api_env):
        client = api_env
        r = client.post("/api/predict/eta", json={"distance_km": -5})
        assert r.status_code == 422

    def test_predict_anomaly(self, api_env):
        client = api_env
        obs = [{"speed_kmh": 80, "acceleration_kmh_s": 0.5, "fuel_rate_lph": 10,
                "engine_load_pct": 50, "engine_temp_c": 90,
                "ambient_temp_c": 18, "idle_time_s": 0}]
        r = client.post("/api/predict/anomaly", json={"observations": obs})
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert "anomaly_flag" in body[0]

    def test_predict_anomaly_invalid_payload(self, api_env):
        client = api_env
        r = client.post("/api/predict/anomaly", json={"observations": []})
        assert r.status_code == 422

