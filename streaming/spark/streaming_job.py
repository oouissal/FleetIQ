"""FleetIQ Spark Structured Streaming job.

Pipeline per event domain (telemetry / gps / delivery):

    Kafka topic (or local parquet files in `file` mode)
        -> parse + normalize timestamps
        -> validate (declarative rules; errors collected in array column)
            ├─ valid   -> dedupe -> BRONZE (raw parquet)
            │               -> enrich -> SILVER (cleaned parquet)
            │                   -> windowed aggregates -> GOLD
            └─ invalid -> BRONZE/_invalid (never silently dropped)
                           + counted into GOLD/data_quality

Usage:
    # against Kafka (production path, run inside docker-compose)
    spark-submit streaming/spark/streaming_job.py --mode kafka

    # against local parquet files (development / tests)
    spark-submit streaming/spark/streaming_job.py --mode file \
        --input data/raw

Configuration is read from the environment (see streaming/spark/config.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Make the project root importable with `python script.py` AND `spark-submit
# script.py` (the latter does not add the script directory to sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming import StreamingQuery, StreamingQueryListener
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from streaming.spark import aggregates, enrichment
from streaming.spark.config import SparkConfig
from streaming.spark.schemas import DELIVERY_SCHEMA, GPS_SCHEMA, TELEMETRY_SCHEMA
from streaming.spark.validation import rule_expressions

log = logging.getLogger("streaming.spark")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s - %(message)s")


def _wire_schema(schema: StructType, string_fields: set[str]) -> StructType:
    """Timestamps arrive as ISO strings on the wire; cast later."""
    return StructType([
        StructField(f.name, StringType(), f.nullable) if f.name in string_fields else f
        for f in schema.fields
    ])


WIRE_SCHEMAS = {
    "telemetry": _wire_schema(TELEMETRY_SCHEMA, {"timestamp"}),
    "gps": _wire_schema(GPS_SCHEMA, {"timestamp"}),
    "delivery": _wire_schema(DELIVERY_SCHEMA, {"timestamp", "planned_arrival_time"}),
}
TIMESTAMP_COLS = {"telemetry": ["timestamp"], "gps": ["timestamp"],
                  "delivery": ["timestamp", "planned_arrival_time"]}
TOPICS = {"telemetry": "fleet.telemetry", "gps": "fleet.gps", "delivery": "fleet.delivery"}

# Historical deliveries.parquet uses a different layout (no event_id /
# timestamp columns; arrival times instead). Types below mirror the
# generator's pandas output exactly. Adapted to wire format in read_source.
FILE_DELIVERY_SCHEMA = StructType([
    StructField("delivery_id", StringType()),
    StructField("route_id", StringType()),
    StructField("vehicle_id", StringType()),
    StructField("stop_index", LongType()),
    StructField("stop_fraction", DoubleType()),
    StructField("parcels", LongType()),
    StructField("planned_dispatch_time", StringType()),
    StructField("planned_arrival_time", StringType()),
    StructField("actual_arrival_time", StringType()),
    StructField("status", StringType()),
    StructField("leg_distance_km", DoubleType()),
    StructField("duration_minutes", DoubleType()),
    StructField("delayed", BooleanType()),
    StructField("weather", StringType()),
    StructField("traffic_multiplier", DoubleType()),
])


class _ProgressListener(StreamingQueryListener):
    """Structured logging of every micro-batch (observability)."""

    def onQueryProgress(self, event) -> None:
        try:
            p = event.progress
            log.info(
                "streaming batch=%s input_rows=%s processed_rows=%s duration_ms=%s",
                p.batchId, p.numInputRows, p.numInputRows,
                p.get("durationMs", {}).get("total", "?"),
            )
        except Exception:
            log.exception("progress listener error (non-fatal)")

    def onQueryStarted(self, event) -> None:
        log.info("streaming query started: %s", event)

    def onQueryTerminated(self, event) -> None:
        log.info("streaming query terminated: %s", event)


# ---------------------------------------------------------------------------
# Session + sources
# ---------------------------------------------------------------------------
def build_spark_session(cfg: SparkConfig, app_name: str = "FleetIQStreaming") -> SparkSession:
    builder = (SparkSession.builder
               .appName(app_name)
               .config("spark.sql.session.timeZone", "UTC")
               .config("spark.sql.streaming.forceDeleteTempCheckpointLocation", "true"))
    if cfg.lake_base.startswith("s3a://"):
        builder = (builder
                   .config("spark.hadoop.fs.s3a.endpoint", cfg.s3_endpoint)
                   .config("spark.hadoop.fs.s3a.access.key", cfg.s3_access_key)
                   .config("spark.hadoop.fs.s3a.secret.key", cfg.s3_secret_key)
                   .config("spark.hadoop.fs.s3a.path.style.access", str(cfg.s3_path_style_access).lower())
                   .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
                   .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem"))
    spark = builder.getOrCreate()
    spark.streams.addListener(_ProgressListener())
    spark.sparkContext.setLogLevel("WARN")
    return spark


def read_source(spark: SparkSession, cfg: SparkConfig, event_type: str,
                mode: str, input_dir: str | None = None) -> DataFrame:
    """Return the raw event stream for one domain (wire format)."""
    wire = WIRE_SCHEMAS[event_type]
    if mode == "kafka":
        return (spark.readStream
                .format("kafka")
                .option("kafka.bootstrap.servers", cfg.kafka_bootstrap)
                .option("subscribe", TOPICS[event_type])
                .option("startingOffsets", "latest")
                .option("maxOffsetsPerTrigger", cfg.max_events_per_trigger)
                .load()
                .select(F.from_json(F.col("value").cast("string"), wire).alias("event"))
                .select("event.*"))
    if mode == "file":
        if not input_dir:
            raise ValueError("--input is required in file mode")
        # Streaming file sources require a DIRECTORY of parquet files
        # (scripts/prepare_stream_input.py produces this layout).
        path = f"{input_dir}/events/{event_type}"
        if event_type == "delivery":
            # historical deliveries.parquet -> wire format
            df = (spark.readStream
                  .format("parquet")
                  .schema(FILE_DELIVERY_SCHEMA)
                  .option("maxFilesPerTrigger", 4)
                  .load(path))
            return (df
                    .withColumn("timestamp", F.col("actual_arrival_time"))
                    .withColumn("event_id", F.concat("delivery_id", F.lit("_"), "status"))
                    .withColumn("event_type", F.lit("delivery"))
                    .withColumn("stop_index", F.col("stop_index").cast("int"))
                    .withColumn("parcels", F.col("parcels").cast("int"))
                    .select([f.name for f in WIRE_SCHEMAS["delivery"].fields]))
        return (spark.readStream
                .format("parquet")
                .schema(WIRE_SCHEMAS[event_type])
                .option("maxFilesPerTrigger", 4)
                .load(path))
    raise ValueError(f"Unknown mode: {mode!r}")


def normalize(df: DataFrame, event_type: str) -> DataFrame:
    """Cast ISO-8601 string timestamps to TimestampType (idempotent)."""
    for col in TIMESTAMP_COLS[event_type]:
        if col in df.columns:
            df = df.withColumn(
                col,
                F.when(F.col(col).cast("string").isNull(), F.lit(None))
                .otherwise(F.to_timestamp(F.col(col).cast("string"))),
            )
    return df


def with_validation(df: DataFrame, event_type: str) -> DataFrame:
    """Attach a validation_errors array column (empty = valid)."""
    fails = [
        F.when(~F.expr(expr), F.lit(name))
        for name, expr in rule_expressions(event_type).items()
    ]
    errors = F.array_remove(F.array(*fails), F.lit(None))
    return df.withColumn("validation_errors", errors)


# ---------------------------------------------------------------------------
# Query builders (one domain)
# ---------------------------------------------------------------------------
def build_domain_queries(spark: SparkSession, cfg: SparkConfig,
                         event_type: str, mode: str,
                         input_dir: str | None = None) -> list[StreamingQuery]:
    raw = read_source(spark, cfg, event_type, mode, input_dir)
    raw = normalize(raw, event_type)
    validated = with_validation(raw, event_type)
    trigger = {"availableNow": True} if mode == "file" else {"processingTime": cfg.trigger}

    valid = validated.filter(F.size("validation_errors") == 0).drop("validation_errors")
    invalid = validated.filter(F.size("validation_errors") > 0)

    # event-time watermark + dedupe (at-least-once redelivery safety)
    valid = (valid
             .withWatermark("timestamp", cfg.watermark)
             .dropDuplicates(["event_id"]))

    ck = f"{cfg.checkpoint_path}/bronze-{event_type}"
    bronze_q = (valid.writeStream
                .format("parquet")
                .option("checkpointLocation", ck)
                .outputMode("append")
                .queryName(f"bronze-{event_type}")
                .trigger(**trigger)
                .start(cfg.bronze_path + f"/{event_type}"))

    invalid_q = (invalid.writeStream
                 .format("parquet")
                 .option("checkpointLocation", f"{cfg.checkpoint_path}/invalid-{event_type}")
                 .outputMode("append")
                 .queryName(f"invalid-{event_type}")
                 .trigger(**trigger)
                 .start(cfg.bronze_invalid + f"/{event_type}"))

    queries = [bronze_q, invalid_q]

    # silver enrichment
    if event_type == "telemetry":
        silver = enrichment.enrich_telemetry(valid, cfg.watermark)
    elif event_type == "gps":
        silver = enrichment.enrich_gps(valid, cfg.watermark)
    else:
        silver = valid  # deliveries: already clean; gold computed from them
    silver_q = (silver.writeStream
                .format("parquet")
                .option("checkpointLocation", f"{cfg.checkpoint_path}/silver-{event_type}")
                .outputMode("append")
                .queryName(f"silver-{event_type}")
                .trigger(**trigger)
                .start(cfg.silver_path + f"/{event_type}"))
    queries.append(silver_q)

    # gold aggregates
    if event_type == "telemetry":
        for name, path, agg_fn in [
            ("gold-fleet-kpis", cfg.gold_fleet_kpis, aggregates.fleet_kpis),
            ("gold-route-performance", cfg.gold_route_performance, aggregates.route_performance),
            ("gold-vehicle-health", cfg.gold_vehicle_health, aggregates.vehicle_health),
        ]:
            q = (agg_fn(silver).writeStream
                 .format("parquet")
                 .option("checkpointLocation", f"{cfg.checkpoint_path}/{name}")
                 .outputMode("append")
                 .queryName(name)
                 .trigger(**trigger)
                 .start(path))
            queries.append(q)
    elif event_type == "delivery":
        q = (aggregates.delivery_performance(silver).writeStream
             .format("parquet")
             .option("checkpointLocation", f"{cfg.checkpoint_path}/gold-delivery-performance")
             .outputMode("append")
             .queryName("gold-delivery-performance")
             .trigger(**trigger)
             .start(cfg.gold_delivery_performance))
        queries.append(q)

    return queries


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["kafka", "file"], default="kafka",
                   help="kafka: read from Kafka topics; file: read local parquet files.")
    p.add_argument("--input", default=None,
                   help="file mode: directory containing telemetry.parquet / "
                        "gps.parquet / deliveries.parquet")
    p.add_argument("--duration", type=int, default=0,
                   help="kafka mode: stop after N seconds (0 = run forever).")
    p.add_argument("--domains", default="telemetry,gps,delivery",
                   help="comma-separated event domains to process.")
    args = p.parse_args(argv)

    cfg = SparkConfig()
    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    for d in domains:
        if d not in WIRE_SCHEMAS:
            raise SystemExit(f"Unknown domain {d!r}; expected one of {list(WIRE_SCHEMAS)}")

    spark = build_spark_session(cfg)
    queries: list[StreamingQuery] = []
    for domain in domains:
        queries.extend(build_domain_queries(spark, cfg, domain, args.mode, args.input))

    log.info("Started %s streaming queries (mode=%s, domains=%s)",
             len(queries), args.mode, domains)

    if args.mode == "file":
        while any(q.isActive for q in queries):
            time.sleep(1)
        log.info("File-mode queries completed.")
        spark.stop()
        return 0

    if args.duration > 0:
        log.info("Running for %s seconds...", args.duration)
        deadline = time.time() + args.duration
        while time.time() < deadline and any(q.isActive for q in queries):
            time.sleep(1)
        for q in queries:
            q.stop()
        spark.stop()
        return 0

    try:
        spark.streams.awaitAnyTermination()
    except KeyboardInterrupt:
        log.info("Interrupted; stopping queries.")
        for q in queries:
            q.stop()
    spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


