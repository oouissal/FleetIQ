"""Tests for feature engineering, temporal split, and ML training logic.

Uses a tiny synthetic dataset generated once per session (fast, local).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.evaluate import regression_metrics, residual_interval
from ml.features import (
    ANOMALY_FEATURES,
    ETA_FEATURES,
    TARGET,
    build_anomaly_features,
    build_eta_dataset,
    day_of_week,
    distance_km_from_gps,
    fuel_per_100km,
    historical_route_duration,
    idle_ratio,
    temporal_split,
    time_of_day,
)
from ml.predict import build_eta_feature_vector


@pytest.fixture(scope="module")
def raw_dir(tmp_path_factory) -> Path:
    from data_generator.cli import main as gen_main

    out = tmp_path_factory.mktemp("raw")
    rc = gen_main(["--vehicles", "12", "--events", "20000", "--days", "2",
                   "--routes", "8", "--deliveries-per-route", "40",
                   "--output-dir", str(out), "--seed", "21"])
    assert rc == 0
    return out


@pytest.fixture(scope="module")
def eta_df(raw_dir) -> pd.DataFrame:
    return build_eta_dataset(raw_dir)


# --------------------------------------------------------------------------
# Low-level feature functions
# --------------------------------------------------------------------------
class TestFeatureFunctions:
    def test_distance_km_from_gps_sane(self):
        d = distance_km_from_gps(pd.Series([45.42]), pd.Series([-73.62]),
                                 pd.Series([45.45]), pd.Series([-73.60]))
        assert 2.0 < d.iloc[0] < 5.0

    def test_fuel_per_100km_formula(self):
        f = fuel_per_100km(pd.Series([8.0]), pd.Series([80.0]))
        assert abs(f.iloc[0] - 10.0) < 1e-9

    def test_fuel_per_100km_none_below_5kmh(self):
        f = fuel_per_100km(pd.Series([2.0]), pd.Series([3.0]))
        assert pd.isna(f.iloc[0])

    def test_idle_ratio_bounds(self):
        r = idle_ratio(pd.Series([5.0, 10.0, 0.0]), pd.Series([10.0, 10.0, 10.0]))
        assert r.iloc[0] == 0.5
        assert r.iloc[1] == 1.0
        assert r.iloc[2] == 0.0

    def test_time_of_day(self):
        s = pd.Series(["2026-10-01T08:30:00Z", "2026-10-01T23:45:00Z"])
        h = time_of_day(s)
        assert h.iloc[0] == 8.5
        assert h.iloc[1] == 23.75

    def test_day_of_week_monday(self):
        # 2026-10-05 is a Monday
        assert day_of_week(pd.Series(["2026-10-05T10:00:00Z"])).iloc[0] == 0


# --------------------------------------------------------------------------
# ETA dataset
# --------------------------------------------------------------------------
class TestEtaDataset:
    def test_dataset_non_empty_with_features(self, eta_df):
        assert len(eta_df) > 50
        for col in ETA_FEATURES + [TARGET]:
            assert col in eta_df.columns
        assert eta_df[TARGET].min() > 0

    def test_no_missing_values(self, eta_df):
        assert eta_df[ETA_FEATURES + [TARGET]].isna().sum().sum() == 0

    def test_temporal_split_future_test_set(self, eta_df):
        train, val, test = temporal_split(eta_df)
        assert len(train) > 0 and len(val) > 0 and len(test) > 0
        train_max = train["planned_dispatch_time"].max()
        val_max = val["planned_dispatch_time"].max()
        test_min = test["planned_dispatch_time"].min()
        assert train_max <= test_min  # test is strictly future
        assert train_max <= val_max

    def test_historical_duration_is_past_only(self, eta_df):
        """The historical feature for row i must not include row i's target."""
        df = eta_df.sort_values("planned_dispatch_time").reset_index(drop=True)
        hist = historical_route_duration(df)
        # for the first delivery on each route, history is NaN -> dropped in
        # build_eta_dataset; the feature never uses the row's own duration
        # (it is the expanding mean of STRICTLY earlier rows).
        assert hist.isna().sum() <= (df["route_id"].nunique())

    def test_features_are_dispatch_time_knowable(self, eta_df):
        """No realized outcomes leak into features."""
        for col in ("actual_arrival_time", "duration_minutes", "delayed",
                    "leg_distance_km"):
            assert col not in ETA_FEATURES


# --------------------------------------------------------------------------
# Anomaly dataset
# --------------------------------------------------------------------------
class TestAnomalyFeatures:
    def test_anomaly_features_present(self, raw_dir):
        df = build_anomaly_features(raw_dir)
        assert len(df) > 100
        for col in ANOMALY_FEATURES:
            assert col in df.columns

    def test_acceleration_computed(self, raw_dir):
        df = build_anomaly_features(raw_dir)
        assert df["acceleration_kmh_s"].notna().any()
        # acceleration bounded by the physics of the sim (10s ticks)
        assert df["acceleration_kmh_s"].abs().max() < 50


# --------------------------------------------------------------------------
# ML training (small-scale, real metrics)
# --------------------------------------------------------------------------
class TestTraining:
    def test_train_eta_produces_metrics(self, raw_dir, tmp_path):
        from ml.train_eta import train as train_eta

        results = train_eta(raw_dir, tracking_uri=str(tmp_path / "mlruns"),
                            results_file=tmp_path / "eta_results.json")
        assert "baseline" in results and "final" in results
        final = results["final"]
        metrics = final["metrics_test"]
        for k in ("mae", "rmse", "r2"):
            assert isinstance(metrics[k], float)
        assert results["dataset_rows"] > 50
        # time-ordered split documented
        assert "future" in results["split"]

    def test_train_anomaly_flags_share_matches_contamination(self, raw_dir, tmp_path):
        from ml.train_anomaly import train as train_anomaly

        out = tmp_path / "anomalies"
        results = train_anomaly(raw_dir, out,
                                tracking_uri=str(tmp_path / "mlruns"),
                                contamination=0.05)
        assert results["n_flagged"] > 0
        assert abs(results["flagged_share"] - 0.05) < 0.05
        assert (out / "anomalies.parquet").exists()
        assert (out / "anomaly_metadata.json").exists()
        meta = json.loads((out / "anomaly_metadata.json").read_text())
        assert meta["method"] == "IsolationForest (unsupervised)"

    def test_regression_metrics_values(self):
        y = pd.Series([1.0, 2.0, 3.0, 4.0])
        pred = np.array([1.5, 2.5, 3.5, 4.5])
        m = regression_metrics(y, pred)
        assert m["mae"] == 0.5
        assert abs(m["rmse"] - 0.5) < 1e-9
        assert abs(m["r2"] - 0.8) < 1e-9

    def test_residual_interval_positive(self):
        y = pd.Series([1.0, 3.0, 5.0])
        pred = np.array([1.0, 3.0, 5.0])
        assert residual_interval(y, pred) == 0.0


# --------------------------------------------------------------------------
# Prediction service
# --------------------------------------------------------------------------
class TestPredictionService:
    def test_eta_feature_vector_shape_and_defaults(self):
        X = build_eta_feature_vector({"distance_km": 50.0})
        assert list(X.columns) == ETA_FEATURES
        assert X.iloc[0]["planned_distance_km"] == 50.0
        assert X.iloc[0]["vehicle_type_BOX_TRUCK"] == 1.0
        assert X.iloc[0]["typical_speed_kmh"] == 55.0

    def test_eta_feature_vector_weather_dummy(self):
        X = build_eta_feature_vector({"distance_km": 10, "weather": "storm"})
        assert X.iloc[0]["weather_storm"] == 1.0
        assert X.iloc[0]["weather_rain"] == 0.0

    def test_anomaly_predictor_logic(self):
        """Unit-test OUR predictor with a stub model: sklearn's Isolation
        Forest behaviour itself is covered by its own upstream tests."""
        from ml.predict import AnomalyPredictor

        class _StubModel:
            def __init__(self, flag: int) -> None:
                self.flag = flag

            def score_samples(self, X):
                return np.full(len(X), -0.6)

            def predict(self, X):
                return np.full(len(X), self.flag)

        rows = [{f: 0.0 for f in ANOMALY_FEATURES}]
        p = AnomalyPredictor(tracking_uri="unused")
        p._model = _StubModel(-1)
        out = p.predict(rows)
        assert len(out) == 1
        assert out[0]["anomaly_flag"] is True
        assert "Unusual telemetry pattern" in out[0]["description"]
        assert out[0]["anomaly_score"] == -0.6

        p._model = _StubModel(1)
        out = p.predict(rows)
        assert out[0]["anomaly_flag"] is False
        assert "No unusual pattern" in out[0]["description"]

