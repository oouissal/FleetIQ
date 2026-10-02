"""Spark Structured Streaming configuration (env-driven)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SparkConfig(BaseSettings):
    """All paths/endpoints for the streaming job; env-overridable."""

    model_config = SettingsConfigDict(
        env_prefix="FLEETIQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Kafka
    kafka_bootstrap: str = "localhost:9092"

    # Data lake locations.
    # In Docker: s3a://bronze etc. (MinIO). Locally: file paths.
    lake_base: str = "s3a://"
    bronze_path: str = "s3a://bronze"
    silver_path: str = "s3a://silver"
    gold_path: str = "s3a://gold"
    checkpoint_path: str = "/tmp/fleetiq-checkpoints"

    # MinIO / S3 credentials (only used with s3a:// paths)
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_path_style_access: bool = True

    # Streaming semantics
    window_duration: str = "5 minutes"
    watermark: str = "10 minutes"
    trigger: str = "10 seconds"
    max_events_per_trigger: int = 50000

    @property
    def bronze_telemetry(self) -> str:
        return f"{self.bronze_path}/telemetry"

    @property
    def bronze_gps(self) -> str:
        return f"{self.bronze_path}/gps"

    @property
    def bronze_delivery(self) -> str:
        return f"{self.bronze_path}/delivery"

    @property
    def bronze_invalid(self) -> str:
        return f"{self.bronze_path}/_invalid"

    @property
    def silver_telemetry(self) -> str:
        return f"{self.silver_path}/telemetry"

    @property
    def silver_gps(self) -> str:
        return f"{self.silver_path}/gps"

    @property
    def gold_fleet_kpis(self) -> str:
        return f"{self.gold_path}/fleet_kpis"

    @property
    def gold_route_performance(self) -> str:
        return f"{self.gold_path}/route_performance"

    @property
    def gold_delivery_performance(self) -> str:
        return f"{self.gold_path}/delivery_performance"

    @property
    def gold_vehicle_health(self) -> str:
        return f"{self.gold_path}/vehicle_health"
