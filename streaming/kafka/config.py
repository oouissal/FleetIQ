"""Kafka configuration via environment variables (no hard-coded secrets)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from streaming.kafka.schemas import (
    TOPIC_DELIVERY,
    TOPIC_GPS,
    TOPIC_TELEMETRY,
)


class KafkaConfig(BaseSettings):
    """Connection + topic configuration, overridable via environment."""

    model_config = SettingsConfigDict(
        env_prefix="KAFKA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bootstrap_servers: str = "localhost:9092"
    security_protocol: str = "PLAINTEXT"
    topic_telemetry: str = TOPIC_TELEMETRY
    topic_gps: str = TOPIC_GPS
    topic_delivery: str = TOPIC_DELIVERY
    # producer tuning
    linger_ms: int = 5
    batch_size: int = 16_384
    request_timeout_ms: int = 10_000

    @property
    def topics(self) -> list[str]:
        return [self.topic_telemetry, self.topic_gps, self.topic_delivery]


def get_kafka_config() -> KafkaConfig:
    """Convenience accessor (cached per process)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = KafkaConfig()
    return _CACHE


_CACHE: KafkaConfig | None = None
