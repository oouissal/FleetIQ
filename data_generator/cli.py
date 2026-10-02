"""Command-line interface for the FleetIQ synthetic data generator.

Two modes:

Historical (default)
    python -m data_generator --vehicles 500 --events 2000000 --seed 42
    Simulates the fleet and writes parquet files (vehicles, drivers, routes,
    deliveries, telemetry, gps) plus a metadata.json to ``--output-dir``.

Streaming
    python -m data_generator --stream --speed 50 --vehicles 100
    Produces events to the Kafka topics fleet.telemetry / fleet.gps /
    fleet.delivery at roughly ``--speed`` events per second.

Reproducibility: identical arguments + seed produce identical events.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data_generator.models import Delivery, Hub, Route, Vehicle
from data_generator.simulation import (
    FleetSimulator,
    make_deliveries,
    make_hubs,
    make_routes,
    make_vehicles,
)

log = logging.getLogger("data_generator")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

CHUNK_SIZE = 100_000


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
class ChunkedParquetWriter:
    """Appends pandas DataFrames to a single parquet file chunk by chunk."""

    def __init__(self, path: Path, schema: pa.Schema | None = None) -> None:
        self.path = path
        self.schema = schema
        self.writer: pq.ParquetWriter | None = None
        self.rows = 0

    def write(self, df: pd.DataFrame) -> None:
        if df.empty:
            return
        table = pa.Table.from_pandas(df, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path, table.schema)
        elif self.schema is not None:
            table = table.cast(self.schema)
        self.writer.write_table(table)
        self.rows += len(df)

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()


def _df_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(records)


def write_simulation_output(out_dir: Path, vehicles: list[Vehicle],
                            drivers: list, hubs: list[Hub], routes: list[Route],
                            deliveries: list[Delivery],
                            telemetry: list[dict[str, Any]],
                            gps: list[dict[str, Any]]) -> dict[str, Any]:
    """Write all simulation artifacts as parquet files + metadata.json."""
    out_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([asdict(v) for v in vehicles]).to_parquet(out_dir / "vehicles.parquet", index=False)
    pd.DataFrame([asdict(d) for d in drivers]).to_parquet(out_dir / "drivers.parquet", index=False)
    pd.DataFrame([{
        "hub_id": h.hub_id, "name": h.name,
        "latitude": h.location.latitude, "longitude": h.location.longitude,
    } for h in hubs]).to_parquet(out_dir / "hubs.parquet", index=False)
    pd.DataFrame([{
        "route_id": r.route_id,
        "origin_hub_id": r.origin_hub_id,
        "destination_hub_id": r.destination_hub_id,
        "waypoints": json.dumps([[w.latitude, w.longitude] for w in r.waypoints]),
        "distance_km": r.distance_km,
        "congestion_factor": r.congestion_factor,
        "typical_duration_min": r.typical_duration_min,
    } for r in routes]).to_parquet(out_dir / "routes.parquet", index=False)

    completed = [d for d in deliveries if d.status is not None]
    pd.DataFrame([{
        "delivery_id": d.delivery_id,
        "route_id": d.route_id,
        "vehicle_id": d.vehicle_id,
        "stop_index": d.stop_index,
        "stop_fraction": d.stop_fraction,
        "parcels": d.parcels,
        "planned_dispatch_time": d.planned_dispatch_time,
        "planned_arrival_time": d.planned_arrival_time,
        "actual_arrival_time": d.actual_arrival_time,
        "status": d.status.value if d.status else None,
        "leg_distance_km": d.leg_distance_km,
        "duration_minutes": d.duration_minutes,
        "delayed": d.delayed,
        "weather": d.weather.value if d.weather else None,
        "traffic_multiplier": d.traffic_multiplier,
    } for d in completed]).to_parquet(out_dir / "deliveries.parquet", index=False)

    tele_path = out_dir / "telemetry.parquet"
    tele_writer = ChunkedParquetWriter(tele_path)
    for i in range(0, len(telemetry), CHUNK_SIZE):
        tele_writer.write(_df_from_records(telemetry[i:i + CHUNK_SIZE]))
    tele_writer.close()

    gps_path = out_dir / "gps.parquet"
    gps_writer = ChunkedParquetWriter(gps_path)
    for i in range(0, len(gps), CHUNK_SIZE):
        gps_writer.write(_df_from_records(gps[i:i + CHUNK_SIZE]))
    gps_writer.close()

    return {
        "vehicles": len(vehicles),
        "drivers": len(drivers),
        "routes": len(routes),
        "deliveries_completed": len(completed),
        "telemetry_events": len(telemetry),
        "gps_events": len(gps),
    }


# ---------------------------------------------------------------------------
# Population builders
# ---------------------------------------------------------------------------
def _parse_start(start: str | None) -> datetime:
    if start:
        dt = datetime.fromisoformat(start)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc).replace(microsecond=0)


def build_population(args: argparse.Namespace) -> tuple[list, list, list, list, list]:
    hubs = make_hubs(args.seed)
    vehicles, drivers = make_vehicles(args.seed, args.vehicles)
    routes = make_routes(args.seed, hubs, count=args.routes)
    deliveries = make_deliveries(args.seed, routes, per_route=args.deliveries_per_route)
    return hubs, vehicles, drivers, routes, deliveries



# ---------------------------------------------------------------------------
# Historical mode
# ---------------------------------------------------------------------------
def run_historical(args: argparse.Namespace) -> int:
    log.info("Generating historical dataset: %s vehicles, %s events, seed=%s",
             args.vehicles, args.events or "unlimited", args.seed)
    hubs, vehicles, drivers, routes, deliveries = build_population(args)
    if args.start:
        start = _parse_start(args.start)
    else:
        start = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
    sim = FleetSimulator(vehicles, drivers, hubs, routes, deliveries,
                         seed=args.seed, start_time=start, sim_days=args.days,
                         dt_seconds=args.dt_seconds)

    telemetry: list[dict[str, Any]] = []
    gps: list[dict[str, Any]] = []
    t0 = time.time()
    n = 0
    for event in sim.run(max_events=args.events or None):
        n += 1
        if event["event_type"] == "telemetry":
            telemetry.append(event)
        elif event["event_type"] == "gps":
            gps.append(event)
        if n % 200_000 == 0:
            log.info("  ... %s events generated (%.1fs elapsed, sim time %s)",
                     n, time.time() - t0, sim.now.isoformat())

    stats = write_simulation_output(Path(args.output_dir), vehicles, drivers,
                                    hubs, routes, deliveries, telemetry, gps)
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "args": {k: v for k, v in vars(args).items()},
        "simulation_start": start.isoformat(),
        "simulation_end": sim.now.isoformat(),
        "events_total": n,
        "counts": stats,
        "note": "Synthetic data generated by data_generator; not real fleet data.",
    }
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    log.info("Wrote dataset to %s in %.1fs: %s", out, time.time() - t0, stats)
    return 0

# ---------------------------------------------------------------------------
# Streaming mode
# ---------------------------------------------------------------------------
def run_stream(args: argparse.Namespace) -> int:
    from streaming.kafka.producer import FleetEventProducer  # local import

    hubs, vehicles, drivers, routes, deliveries = build_population(args)
    start = _parse_start(args.start)
    sim = FleetSimulator(vehicles, drivers, hubs, routes, deliveries,
                         seed=args.seed, start_time=start, sim_days=args.days,
                         dt_seconds=args.dt_seconds)

    producer = FleetEventProducer(bootstrap_servers=args.kafka_bootstrap)
    produced = 0
    t0 = time.time()
    interval = 1.0 / max(1, args.speed)
    try:
        for event in sim.run(max_events=None):
            producer.send(event)
            produced += 1
            if produced % 500 == 0:
                log.info("Streamed %s events (%.1f/s, sim time %s)",
                         produced, produced / max(1.0, time.time() - t0),
                         sim.now.isoformat())
            if args.duration and time.time() - t0 >= args.duration:
                log.info("Reached --duration %ss, stopping.", args.duration)
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        producer.flush()
    log.info("Streamed %s events to Kafka in %.1fs.", produced, time.time() - t0)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="data_generator",
        description="FleetIQ synthetic fleet event generator (historical or streaming).",
    )
    p.add_argument("--vehicles", type=int, default=500,
                   help="Number of vehicles (default: 500).")
    p.add_argument("--events", type=int, default=2_000_000,
                   help="Cap on total telemetry+GPS events in historical mode "
                        "(0 = unlimited, bounded by --days).")
    p.add_argument("--speed", type=int, default=50,
                   help="Streaming mode: target events per second (default: 50).")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for reproducible generation (default: 42).")
    p.add_argument("--days", type=int, default=2,
                   help="Simulated days (historical mode bound; default: 2).")
    p.add_argument("--dt-seconds", type=int, default=10,
                   help="Simulation tick in seconds (default: 10).")
    p.add_argument("--routes", type=int, default=120,
                   help="Number of routes (default: 120).")
    p.add_argument("--deliveries-per-route", type=int, default=40,
                   help="Delivery slots generated per route (default: 40).")
    p.add_argument("--start", type=str, default=None,
                   help="Simulation start time (ISO 8601). Default: now (stream) "
                        "or 2026-10-01T06:00:00 (historical).")
    p.add_argument("--output-dir", type=str, default="data/raw",
                   help="Historical mode: output directory (default: data/raw).")
    p.add_argument("--stream", action="store_true",
                   help="Stream events to Kafka instead of writing files.")
    p.add_argument("--duration", type=int, default=300,
                   help="Streaming mode: max run time in seconds (default: 300).")
    p.add_argument("--kafka-bootstrap", type=str, default="localhost:9092",
                   help="Streaming mode: Kafka bootstrap servers.")
    p.add_argument("--verbose", action="store_true", help="Verbose logging.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.events == 0:
        args.events = None
    if args.stream:
        return run_stream(args)
    return run_historical(args)


if __name__ == "__main__":
    raise SystemExit(main())



