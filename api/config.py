"""API configuration (env-driven; no hard-coded secrets)."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FLEETIQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Data access
    raw_root: str = "data/raw"
    gold_root: str = "data_lake/gold"
    lake_base: str = ""            # "s3a://" when running against MinIO
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # ML
    mlflow_tracking_uri: str = ""  # empty -> local ./mlruns file store
    eta_interval_half_min: float = 25.0
    results_meta_dir: str = "ml/mlruns_meta"
    anomaly_meta_dir: str = "data_lake/gold/anomalies"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:8081,http://localhost"

    # Store cache (freshness vs. latency)
    store_ttl_seconds: int = 15

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def results_meta_path(self) -> Path:
        return Path(self.results_meta_dir)

    @property
    def anomaly_meta_path(self) -> Path:
        return Path(self.anomaly_meta_dir)


_CONFIG: ApiConfig | None = None


def get_config() -> ApiConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = ApiConfig()
    return _CONFIG
