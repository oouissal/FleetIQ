"""Kafka producer for fleet events.

Every event is validated against its Pydantic schema before being produced,
so malformed data never reaches the broker. Events are keyed by vehicle_id
(telemetry/gps) or delivery_id (delivery) so that all events of one entity
stay in the same partition and remain ordered per entity.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic

from streaming.kafka.schemas import topic_for_event, validate_event

log = logging.getLogger("streaming.kafka")


class FleetEventProducer:
    """Thin wrapper around kafka-python with validation + topic routing."""

    def __init__(self, bootstrap_servers: str, security_protocol: str = "PLAINTEXT",
                 linger_ms: int = 5, request_timeout_ms: int = 10_000,
                 validate: bool = True) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.validate = validate
        self._producer: Optional[KafkaProducer] = None
        self._config = {
            "bootstrap_servers": bootstrap_servers.split(","),
            "security_protocol": security_protocol,
            "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
            "key_serializer": lambda k: k.encode("utf-8") if k else None,
            "linger_ms": linger_ms,
            "request_timeout_ms": request_timeout_ms,
            "acks": 1,
            "retries": 3,
        }

    @property
    def producer(self) -> KafkaProducer:
        if self._producer is None:
            try:
                self._producer = KafkaProducer(**self._config)
                log.info("Kafka producer connected to %s", self.bootstrap_servers)
            except Exception as exc:
                log.error("No Kafka brokers reachable at %s: %s",
                          self.bootstrap_servers, exc)
                raise
        return self._producer

    def send(self, event: dict) -> str:
        """Validate + route one event to its topic. Returns the topic."""
        if self.validate:
            validate_event(event)  # raises ValidationError on bad input
        topic = topic_for_event(event)
        key = event.get("vehicle_id") or event.get("delivery_id")
        self.producer.send(topic, key=key, value=event)
        log.debug("produced %s -> %s (key=%s)", event.get("event_id"), topic, key)
        return topic

    def flush(self) -> None:
        if self._producer is not None:
            self._producer.flush()

    def close(self) -> None:
        if self._producer is not None:
            self._producer.flush()
            self._producer.close(timeout=10)
            self._producer = None

    def __enter__(self) -> "FleetEventProducer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def ensure_topics(bootstrap_servers: str, topics: list[str],
                  partitions: int = 3, replication: int = 1) -> None:
    """Idempotently create the fleet topics (useful outside of the container
    init script, e.g. local development)."""
    try:
        admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers.split(","))
    except Exception as exc:  # noqa: BLE001 - no broker = no-op, logged
        log.warning("Could not connect to Kafka admin at %s: %s", bootstrap_servers, exc)
        return
    existing = set(admin.list_topics())
    new_topics = [
        NewTopic(name=t, num_partitions=partitions, replication_factor=replication)
        for t in topics if t not in existing
    ]
    if new_topics:
        admin.create_topics(new_topics=new_topics)
        log.info("Created Kafka topics: %s", [t.name for t in new_topics])
    else:
        log.info("Kafka topics already exist: %s", sorted(topics))
    admin.close()
