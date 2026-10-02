"""Diagnostic consumer: counts events per topic over a time window.

Used to verify the pipeline end-to-end:
    python -m streaming.kafka.consumer --bootstrap localhost:9092 --seconds 30
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter

from kafka import KafkaConsumer
from kafka.structs import TopicPartition

from streaming.kafka.config import get_kafka_config


def consume_counts(bootstrap_servers: str, topics: list[str],
                   seconds: int) -> Counter:
    """Consume from the END of topics for `seconds` and return counts."""
    consumer = KafkaConsumer(
        bootstrap_servers=bootstrap_servers.split(","),
        auto_offset_reset="latest",
        enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=1000,
    )
    partitions = []
    for topic in topics:
        partitions.extend([TopicPartition(topic, p) for p in consumer.partitions_for_topic(topic)])
    consumer.assign(partitions)
    counts: Counter = Counter()
    deadline = time.time() + seconds
    while time.time() < deadline:
        for msg in consumer.poll(timeout_ms=1000).values():
            for record in msg:
                counts[record.topic] += 1
    consumer.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    cfg = get_kafka_config()
    p = argparse.ArgumentParser(description="Count events per topic for N seconds.")
    p.add_argument("--bootstrap", default=cfg.bootstrap_servers)
    p.add_argument("--seconds", type=int, default=20)
    p.add_argument("--topics", default=",".join(cfg.topics))
    args = p.parse_args(argv)
    topics = args.topics.split(",")
    counts = consume_counts(args.bootstrap, topics, args.seconds)
    print(f"Events observed over {args.seconds}s:")
    for topic in topics:
        print(f"  {topic}: {counts.get(topic, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
