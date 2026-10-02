"""Kafka streaming package for FleetIQ.

Topic naming convention: ``fleet.<domain>`` — one topic per event domain,
each topic carrying a single JSON event schema. JSON was chosen over Avro +
Schema Registry deliberately: the first version of the pipeline favours
reliability and simplicity, and Pydantic validation at the consumer side
covers schema enforcement. Avro/Schema Registry would add value only with a
multi-team, strongly-versioned producer ecosystem.
"""

__all__ = ["FleetEventProducer"]
