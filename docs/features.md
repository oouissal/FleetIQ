# Feature Documentation — FleetIQ

Every feature used by the ETA model is documented here with its definition,
data source, leakage risk and purpose. The golden rule: **a feature may only
use information known at prediction (dispatch) time**. Realized outcomes
(actual speed, actual delay) are never used as features.

## ETA model features

| Feature | Definition | Data source | Leakage risk | Purpose |
| --- | --- | --- | --- | --- |
| `planned_distance_km` | Distance from trip start to the delivery stop = `stop_fraction × route.distance_km` | `routes.parquet`, `deliveries.parquet` | None — geometry known at dispatch | Primary driver of duration |
| `typical_speed_kmh` | Route's typical speed = `distance_km / typical_duration_min × 60` | `routes.parquet` | None — historical route average | Baseline speed expectation |
| `congestion_factor` | Route-level chronic congestion multiplier (0.5 light … 2.5 chronic) | `routes.parquet` | None — static route property | Traffic indicator |
| `hour` | Hour + fraction of planned dispatch time | `deliveries.parquet` (`planned_dispatch_time`) | None — planned time | Rush-hour effect |
| `day_of_week` | 0=Monday … 6=Sunday of planned dispatch | same | None | Weekly traffic patterns |
| `parcels` | Number of parcels at the stop | `deliveries.parquet` | None — known before dispatch | Stop workload |
| `stop_index` | Position of the stop in the route | `deliveries.parquet` | None — route planning | Cumulative-trip effect |
| `historical_route_duration_min` | Expanding **past-only** mean of realized durations of *strictly earlier* deliveries on the same route | `deliveries.parquet` | **Low but real** — computed with a strict time-ordered expanding window; each row only sees the past. First deliveries on a route get NaN and are dropped | Historical route ETA |
| `weather_rain` / `weather_storm` | Simulated weather forecast at dispatch (one-hot) | generator state (documented assumption: weather is known at dispatch, like a forecast) | None under the forecast assumption; would be target-adjacent if "weather" meant realized conditions | ETA variation |
| `vehicle_type_*` | One-hot of VAN / BOX_TRUCK / SEMI_TRAILER / REFRIGERATED | `vehicles.parquet` | None | Vehicle capability differences |

Target: `duration_minutes` — realized trip duration from dispatch to stop
arrival (from the simulator's ground truth).

## Leakage audit

* No feature uses `actual_arrival_time`, realized `leg_distance_km`,
  realized `duration_minutes` or realized `traffic_multiplier`.
* Train/validation/test are split **along time**: the test set is strictly
  the future relative to training (see `ml/features.temporal_split`).
* `historical_route_duration_min` is computed **before** splitting but with
  a past-only window, so test rows see only training-period history —
  exactly what would be available in production.

## Reusable low-level features (also used by gold / anomaly pipelines)

| Feature | Definition | Data source | Purpose |
| --- | --- | --- | --- |
| `distance_km_from_gps` | Haversine distance between two coordinate series | `gps.parquet` | Path distance |
| `average_speed_kmh` | distance / duration | computed | Speed KPIs |
| `speed_variance` | Per-vehicle variance of speed | `telemetry.parquet` | Stop-and-go detection |
| `fuel_per_100km` | `fuel_rate_lph × 100 / speed` (speed > 5 only) | `telemetry.parquet` | Fuel economy |
| `idle_ratio` | `idle_time_s / dt_seconds` clipped to 0..1 | `telemetry.parquet` | Idling share |
| `route_delay_rate` | Per-route share of delayed deliveries | `deliveries.parquet` | **Leakage-prone**: must be computed past-only when used as a feature |
| `acceleration_kmh_s` | Speed delta between consecutive events / elapsed time | `telemetry.parquet` (batch) | Anomaly detection |

## Anomaly detection features

`speed_kmh`, `acceleration_kmh_s`, `fuel_rate_lph`, `engine_load_pct`,
`engine_temp_c`, `ambient_temp_c`, `idle_time_s` — standardized before the
Isolation Forest. None of these are labels; see docs/ml-methodology.md.
