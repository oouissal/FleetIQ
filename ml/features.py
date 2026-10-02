"""Feature engineering for FleetIQ (reusable, leakage-controlled).

Every feature is documented in docs/features.md with definition, data
source, leakage risk and purpose. The golden rule used here:

    A feature may only use information that would be KNOWN at prediction
    time. Realized outcomes (actual speed, actual delay, actual weather)
    are never used as features.

Temporal leakage is avoided by (a) computing historical aggregates with a
strict past-only expanding window per route, and (b) splitting
train/validation/test along time BEFORE any aggregation.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("ml.features")

# ---------------------------------------------------------------------------
# Low-level feature functions (documented individually in docs/features.md)
# ---------------------------------------------------------------------------
def distance_km_from_gps(lat1: pd.Series, lon1: pd.Series,
                         lat2: pd.Series, lon2: pd.Series) -> pd.Series:
    """Haversine distance between two series of coordinates (km)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def average_speed_kmh(distance_km: pd.Series, duration_min: pd.Series) -> pd.Series:
    """Average speed = distance / duration (km/h)."""
    return distance_km * 60.0 / duration_min.replace(0, np.nan)


def speed_variance(telemetry: pd.DataFrame) -> pd.Series:
    """Per-vehicle variance of speed (proxy for stop-and-go driving)."""
    return telemetry.groupby("vehicle_id")["speed_kmh"].transform("var")


def fuel_per_100km(fuel_rate_lph: pd.Series, speed_kmh: pd.Series) -> pd.Series:
    """Instantaneous fuel economy estimate (l/100km), valid for speed > 5."""
    out = fuel_rate_lph * 100.0 / speed_kmh.where(speed_kmh > 5)
    return out


def idle_ratio(idle_time_s: pd.Series, dt_seconds: pd.Series) -> pd.Series:
    """Fraction of a tick spent idling (0..1)."""
    return (idle_time_s / dt_seconds.replace(0, np.nan)).clip(0, 1)


def route_delay_rate(deliveries: pd.DataFrame) -> pd.Series:
    """Per-route fraction of delayed deliveries (uses historical outcomes;
    when used as a feature it MUST be computed past-only)."""
    return (deliveries.groupby("route_id")["delayed"]
            .transform(lambda s: s.mean(skipna=True)))


def time_of_day(timestamps: pd.Series) -> pd.Series:
    """Hour of the day (0-23) as float including fractional hour."""
    return pd.to_datetime(timestamps).dt.hour + \
        pd.to_datetime(timestamps).dt.minute / 60.0


def day_of_week(timestamps: pd.Series) -> pd.Series:
    """Day of week (0=Monday .. 6=Sunday)."""
    return pd.to_datetime(timestamps).dt.dayofweek


# ---------------------------------------------------------------------------
# ETA training dataset
# ---------------------------------------------------------------------------
ETA_FEATURES = [
    "planned_distance_km",
    "typical_speed_kmh",
    "congestion_factor",
    "hour",
    "day_of_week",
    "parcels",
    "stop_index",
    "historical_route_duration_min",
    "weather_rain",
    "weather_storm",
    "vehicle_type_VAN",
    "vehicle_type_BOX_TRUCK",
    "vehicle_type_SEMI_TRAILER",
    "vehicle_type_REFRIGERATED",
]
TARGET = "duration_minutes"


def historical_route_duration(deliveries: pd.DataFrame) -> pd.Series:
    """Past-only expanding mean of duration per route.

    For each row, the mean duration of all *strictly earlier* completed
    deliveries on the same route. This is the "historical route ETA" feature
    and is leakage-safe: it only sees the past.
    """
    df = deliveries.sort_values("planned_dispatch_time").reset_index(drop=True)
    df["_order"] = np.arange(len(df))
    df["_cum_sum"] = df.groupby("route_id")["duration_minutes"].cumsum()
    df["_cum_cnt"] = df.groupby("route_id")["duration_minutes"].cumcount()
    df["_prev_mean"] = (df["_cum_sum"] - df["duration_minutes"]) / df["_cum_cnt"]
    out = df.sort_values("_order")["_prev_mean"].reset_index(drop=True)
    out.name = "historical_route_duration_min"
    return out


def build_eta_dataset(raw_dir: Path, seed: int = 42) -> pd.DataFrame:
    """Join deliveries + routes + vehicles into the ETA training set.

    All features use dispatch-time knowledge only:
      * planned_distance_km = stop_fraction * route.distance_km
      * typical_speed_kmh   = route.distance_km / typical_duration_min
      * weather             = simulated forecast at dispatch (documented)
    The target (duration_minutes) is the realized duration to that stop.
    """
    deliveries = pd.read_parquet(raw_dir / "deliveries.parquet")
    routes = pd.read_parquet(raw_dir / "routes.parquet")
    vehicles = pd.read_parquet(raw_dir / "vehicles.parquet")

    df = deliveries.merge(routes[["route_id", "distance_km", "congestion_factor",
                                  "typical_duration_min"]], on="route_id", how="left")
    df = df.merge(vehicles[["vehicle_id", "vehicle_type", "age_years"]],
                  on="vehicle_id", how="left")

    df = df[df["duration_minutes"].notna()].copy()
    df["planned_dispatch_time"] = pd.to_datetime(df["planned_dispatch_time"])
    df["planned_distance_km"] = df["stop_fraction"] * df["distance_km"]
    df["typical_speed_kmh"] = df["distance_km"] / df["typical_duration_min"] * 60.0
    df["hour"] = time_of_day(df["planned_dispatch_time"]).astype(float)
    df["day_of_week"] = day_of_week(df["planned_dispatch_time"]).astype(int)
    df["historical_route_duration_min"] = historical_route_duration(df)
    df["weather_rain"] = (df["weather"] == "rain").astype(int)
    df["weather_storm"] = (df["weather"] == "storm").astype(int)
    df = pd.get_dummies(df, columns=["vehicle_type"], prefix="vehicle_type", dtype=int)
    # small datasets may not contain every vehicle type; add missing dummies
    for col in ETA_FEATURES:
        if col not in df.columns:
            df[col] = 0
    df = df.dropna(subset=ETA_FEATURES + [TARGET])

    # deterministic shuffle-free ordering: sort by dispatch time
    df = df.sort_values("planned_dispatch_time").reset_index(drop=True)
    log.info("ETA dataset: %s rows, %s features", len(df), len(ETA_FEATURES))
    return df


def temporal_split(df: pd.DataFrame, val_frac: float = 0.15,
                   test_frac: float = 0.15) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Time-ordered split: the test set always represents FUTURE observations.

    This is the anti-leakage split: no random shuffling across time.
    """
    df = df.sort_values("planned_dispatch_time").reset_index(drop=True)
    n = len(df)
    test_start = int(n * (1 - test_frac))
    val_start = int(n * (1 - test_frac - val_frac))
    train = df.iloc[:val_start].reset_index(drop=True)
    val = df.iloc[val_start:test_start].reset_index(drop=True)
    test = df.iloc[test_start:].reset_index(drop=True)
    return train, val, test


# ---------------------------------------------------------------------------
# Anomaly detection dataset
# ---------------------------------------------------------------------------
ANOMALY_FEATURES = [
    "speed_kmh",
    "acceleration_kmh_s",
    "fuel_rate_lph",
    "engine_load_pct",
    "engine_temp_c",
    "ambient_temp_c",
    "idle_time_s",
]


def build_anomaly_features(raw_dir: Path) -> pd.DataFrame:
    """Per-event telemetry features for the Isolation Forest.

    acceleration_kmh_s is computed per vehicle over consecutive events.
    Rows with any null feature are dropped (documented).
    """
    tele = pd.read_parquet(raw_dir / "telemetry.parquet")
    tele = tele.sort_values(["vehicle_id", "timestamp"]).reset_index(drop=True)
    tele["timestamp"] = pd.to_datetime(tele["timestamp"])
    g = tele.groupby("vehicle_id")
    tele["prev_speed"] = g["speed_kmh"].shift(1)
    tele["prev_ts"] = g["timestamp"].shift(1)
    dt = (tele["timestamp"] - tele["prev_ts"]).dt.total_seconds()
    tele["acceleration_kmh_s"] = (tele["speed_kmh"] - tele["prev_speed"]) / dt.replace(0, np.nan)
    tele = tele.dropna(subset=ANOMALY_FEATURES)
    tele["idle_time_s"] = tele["idle_time_s"].clip(0, 3600)
    log.info("Anomaly features: %s rows x %s features", len(tele), len(ANOMALY_FEATURES))
    return tele

