# Data Lake Schemas — FleetIQ (Medallion)

Object store: MinIO (S3-compatible). All layers use **Parquet**. Paths:

```
s3://bronze/<event_type>/            raw events (append)
s3://bronze/_invalid/<event_type>/   rejected events + validation errors
s3://silver/<event_type>/            cleaned + enriched events
s3://gold/<table>/                   business aggregates (5-min windows)
s3://gold/anomalies.parquet          ML anomaly scoring (batch)
s3://checkpoints/                    Spark streaming checkpoint state
```

## Bronze — raw events (append-only)

| Table | Columns (JSON fields preserved 1:1) |
| --- | --- |
| `bronze/telemetry` | event_id, vehicle_id, driver_id, route_id, timestamp, speed_kmh, fuel_rate_lph, fuel_level_pct, engine_load_pct, engine_temp_c, ambient_temp_c, mileage_km, idle_time_s, dt_seconds, weather, traffic_multiplier, event_type |
| `bronze/gps` | event_id, vehicle_id, route_id, timestamp, latitude, longitude, accuracy_m, event_type |
| `bronze/delivery` | event_id, delivery_id, vehicle_id, route_id, stop_index, timestamp, status, planned_arrival_time, parcels, weather, event_type |
| `bronze/_invalid/*` | same columns **+ `validation_errors` (array of rule names)** |

Invalid rows are routed to `_invalid` with the failing rule names — they
never silently disappear and are counted in the quality report.

## Silver — cleaned / enriched

Same columns as bronze (valid rows only), deduplicated on `event_id` within
the watermark window, plus:

* telemetry: `fuel_per_100km` = `fuel_rate_lph * 100 / speed` (speed > 5).
* Known limitation: acceleration and GPS point-to-point distance are
  computed in the **batch** pipeline (ml/features.py), because Spark
  Structured Streaming rejects non-time-windowed `LAG` over streaming
  DataFrames. Documented, not hidden.

## Gold — business aggregates (5-minute event-time windows)

### gold/fleet_kpis (per window)
| Column | Type | Meaning |
| --- | --- | --- |
| window_start | timestamp | window start (event time, UTC) |
| active_vehicles | long | approx distinct vehicles with telemetry (rsd 0.02) |
| avg_speed_kmh | double | mean speed |
| avg_fuel_rate_lph | double | mean fuel rate |
| total_distance_km | double | Σ speed × dt / 3600 (documented approximation) |
| total_idle_s | double | Σ idle seconds |
| telemetry_events | long | event count |

### gold/route_performance (per window + route)
window_start, route_id, vehicles_on_route, avg_speed_kmh,
avg_traffic_multiplier, avg_fuel_per_100km, total_distance_km,
total_idle_s, telemetry_events

### gold/vehicle_health (per window + vehicle)
window_start, vehicle_id, avg_speed_kmh, max_speed_kmh,
speed_stddev_kmh, avg_engine_load_pct, max_engine_temp_c, total_idle_s,
fuel_l, telemetry_events, attention_flag
(`temp_alert` / `engine_load_alert` / `excess_idle` / `ok` — **rule-based**,
not ML).

### gold/delivery_performance (per window + route, terminal statuses only)
window_start, route_id, completed_deliveries, on_time, delayed, failed,
avg_delay_minutes, on_time_rate
(delay = arrival − planned arrival).

### gold/anomalies.parquet (batch ML, flat file)
event_id, vehicle_id, timestamp, speed_kmh, acceleration_kmh_s,
fuel_rate_lph, engine_load_pct, engine_temp_c, ambient_temp_c,
idle_time_s, anomaly_score, anomaly_raw_score, anomaly_flag, anomaly_type

### gold/vehicle_snapshot.parquet (batch, flat file)
Latest state per vehicle for the Fleet page: vehicle_id, last_seen,
speed_kmh, fuel_rate_lph, fuel_level_pct, engine_temp_c, mileage_km,
route_id, weather, traffic_multiplier, latitude, longitude, status,
vehicle_type, age_years.
