"""Fleet simulation engine that produces correlated, realistic synthetic events.

Design notes / documented assumptions
-------------------------------------
The simulator is deliberately a *physics-lite* behavioural model. It does not
pretend to be a real fleet, but it encodes the correlations that the ML parts
of this project need in order to be demonstrably learnable:

1. Traffic -> speed
   ``traffic_multiplier(t)`` = hour-of-day rush profile * route congestion
   factor * weekday factor. Effective speed = cruise speed / multiplier.
2. Idle time -> fuel
   Idling burns fuel at ~1.6-3.2 l/h (per vehicle type). Delivery stops and
   congestion generate idle time, so fuel consumption increases with them.
3. Vehicle age -> anomaly probability
   anomaly_risk = min(0.9, base_risk * (1 + 0.35 * age_years)).
4. Weather -> ETA variation
   rain reduces effective speed by 8%, storm by 18%; storm also adds
   stop delays.
5. Engine load correlates with speed; engine temperature rises with load and
   hot/storn weather.

Reproducibility: everything is driven by `random.Random(seed)` and counter
based event ids; no wall-clock or OS randomness is used.

Event cadence: one telemetry + one GPS event per vehicle per 10s sim tick
while the vehicle is active (driving, stopping or idling in a shift).
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from data_generator.models import (
    AnomalyKind,
    Delivery,
    DeliveryStatus,
    Driver,
    GeoPoint,
    Hub,
    HUB_NAMES,
    REGION_CENTER_LAT,
    REGION_CENTER_LON,
    REGION_RADIUS_DEG,
    Route,
    Vehicle,
    VehicleType,
    Weather,
)

# ---------------------------------------------------------------------------
# Behavioural constants (tunable, documented)
# ---------------------------------------------------------------------------
RUSH_HOURS = {7: 1.55, 8: 1.75, 9: 1.45, 16: 1.30, 17: 1.75, 18: 1.60, 19: 1.25}
OFF_PEAK_BASE = 1.0
NIGHT_BASE = 0.85
WEEKEND_FACTOR = 0.90

VEHICLE_TYPE_PARAMS = {
    VehicleType.VAN: {"cruise": 95.0, "idle_lph": 1.6, "fuel_curve_a": 2.1, "fuel_curve_b": 0.011},
    VehicleType.BOX_TRUCK: {"cruise": 85.0, "idle_lph": 2.2, "fuel_curve_a": 3.4, "fuel_curve_b": 0.014},
    VehicleType.SEMI_TRAILER: {"cruise": 90.0, "idle_lph": 2.8, "fuel_curve_a": 5.2, "fuel_curve_b": 0.018},
    VehicleType.REFRIGERATED: {"cruise": 82.0, "idle_lph": 3.2, "fuel_curve_a": 4.6, "fuel_curve_b": 0.016},
}

BEHAVIOR_SPEED_FACTOR = {"cautious": 0.90, "normal": 1.0, "aggressive": 1.08}
WEATHER_SPEED_FACTOR = {Weather.CLEAR: 1.0, Weather.RAIN: 0.92, Weather.STORM: 0.82}
WEATHER_DAY_PROB = [(Weather.CLEAR, 0.74), (Weather.RAIN, 0.20), (Weather.STORM, 0.06)]

STOP_IDLE_MINUTES = (2.0, 8.0)  # delivery stop duration range
LIGHT_IDLE_PROB = 0.05  # chance of a short traffic-light idle per tick when congested
ANOMALY_PROFILES = [AnomalyKind.TEMP_DRIFT, AnomalyKind.FUEL_ANOMALY,
                    AnomalyKind.ENGINE_OVERLOAD, AnomalyKind.SPEED_SENSOR_NOISE]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class FleetSimulator:
    """Generates a stream of telemetry / GPS / delivery events for a fleet."""

    def __init__(self, vehicles: list[Vehicle], drivers: list[Driver],
                 hubs: list[Hub], routes: list[Route], deliveries: list[Delivery],
                 seed: int, start_time: datetime, sim_days: int,
                 dt_seconds: int = 10) -> None:
        self.rng = random.Random(seed)
        self.vehicles = vehicles
        self.drivers = {d.vehicle_id: d for d in drivers}
        self.hubs = {h.hub_id: h for h in hubs}
        self.routes = {r.route_id: r for r in routes}
        self.deliveries = {d.delivery_id: d for d in deliveries}
        self.start_time = start_time.replace(tzinfo=timezone.utc)
        self.sim_days = sim_days
        self.dt_seconds = dt_seconds
        self.end_time = self.start_time + timedelta(days=sim_days)

        # weather cache: one weather state per (day, half) -> more realistic
        self._weather_cache: dict[str, Weather] = {}

        # per-vehicle mutable state
        self._state: dict[str, dict[str, Any]] = {}
        for v in self.vehicles:
            self._state[v.vehicle_id] = self._init_vehicle_state(v)

        self._event_counter = 0
        self.now: datetime = self.start_time

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _init_vehicle_state(v: Vehicle) -> dict[str, Any]:
        return {
            "vehicle": v,
            "status": "IDLE",
            "route_id": None,
            "route": None,
            "trip_started_at": None,
            "leg_start_distance": 0.0,
            "distance_from_start": 0.0,
            "seg_index": 0,
            "seg_remaining_km": 0.0,
            "position": None,
            "next_delivery_idx": 0,
            "trip_deliveries": [],
            "stop_remaining_s": 0.0,
            "mileage_km": 30000.0 + v.age_years * 38000.0,
            "fuel_level_pct": 100.0,
            "fuel_used_l": 0.0,
            "total_idle_s": 0,
            "anomaly_active": None,
            "anomaly_until": None,
            "weather": Weather.CLEAR,
            "traffic": 1.0,
        }

    # ------------------------------------------------------------- utilities
    def _weather_for(self, dt: datetime) -> Weather:
        key = f"{dt.date()}-{0 if dt.hour < 12 else 1}"
        if key not in self._weather_cache:
            self._weather_cache[key] = self.rng.choices(
                [w for w, _ in WEATHER_DAY_PROB],
                weights=[p for _, p in WEATHER_DAY_PROB],
            )[0]
        return self._weather_cache[key]

    @staticmethod
    def _traffic_multiplier(dt: datetime, congestion_factor: float) -> float:
        rush = RUSH_HOURS.get(dt.hour, OFF_PEAK_BASE if 6 <= dt.hour <= 21 else NIGHT_BASE)
        if dt.weekday() >= 5:
            rush *= WEEKEND_FACTOR
        return rush * congestion_factor

    def _cruise_speed(self, v: Vehicle, dt: datetime, weather: Weather,
                      traffic: float) -> float:
        params = VEHICLE_TYPE_PARAMS[v.vehicle_type]
        driver = self.drivers[v.vehicle_id]
        speed = params["cruise"] * BEHAVIOR_SPEED_FACTOR[driver.behavior]
        speed *= WEATHER_SPEED_FACTOR[weather]
        speed /= max(1.0, traffic)
        speed *= self.rng.uniform(0.95, 1.05)  # micro variation
        return speed

    def _fuel_rate_lph(self, v: Vehicle, speed_kmh: float, idle_s: float) -> float:
        """Fuel rate model: idle burn + linear + quadratic speed term."""
        params = VEHICLE_TYPE_PARAMS[v.vehicle_type]
        moving = max(0.0, speed_kmh)
        rate = params["idle_lph"] + params["fuel_curve_a"] * moving / 100.0 \
            + params["fuel_curve_b"] * (moving ** 2) / 100.0
        if v.anomaly_profile == AnomalyKind.FUEL_ANOMALY and self._is_anomaly_active(v.vehicle_id):
            rate *= self.rng.uniform(1.25, 1.7)
        return rate

    def _is_anomaly_active(self, vehicle_id: str) -> bool:
        st = self._state[vehicle_id]
        return st["anomaly_active"] is not None and self.now < st["anomaly_until"]

    def _maybe_trigger_anomaly(self, vehicle_id: str) -> None:
        st = self._state[vehicle_id]
        v = st["vehicle"]
        if v.anomaly_profile == AnomalyKind.NONE:
            return
        if st["anomaly_active"] is None and st["status"] == "DRIVING":
            if self.rng.random() < v.anomaly_risk / 40.0:  # per-tick probability
                st["anomaly_active"] = v.anomaly_profile
                st["anomaly_until"] = self.now + timedelta(minutes=self.rng.uniform(8, 35))

    # ------------------------------------------------------------- lifecycle
    def _assign_trip(self, vehicle_id: str) -> None:
        """Assign a route + its deliveries to an idle vehicle during shift."""
        st = self._state[vehicle_id]
        v = st["vehicle"]
        driver = self.drivers[vehicle_id]
        hour = self.now.hour
        if not (driver.shift_start_hour <= hour < driver.shift_start_hour + driver.shift_duration_hours):
            return
        route = self.rng.choice(list(self.routes.values()))
        trip_dels = [d for d in self.deliveries.values()
                     if d.route_id == route.route_id and d.status is None
                     and d.vehicle_id is None]
        if not trip_dels:
            return
        trip_dels = sorted(trip_dels, key=lambda d: d.stop_fraction)[: self.rng.randint(4, 10)]
        for d in trip_dels:
            d.vehicle_id = vehicle_id  # claim deliveries for this trip
        origin = self.hubs[route.origin_hub_id].location
        st.update({
            "status": "DRIVING",
            "route_id": route.route_id,
            "route": route,
            "trip_started_at": self.now,
            "leg_start_distance": 0.0,
            "distance_from_start": 0.0,
            "seg_index": 0,
            "seg_remaining_km": self._segment_length_km(route, 0, origin),
            "position": GeoPoint(origin.latitude, origin.longitude),
            "next_delivery_idx": 0,
            "trip_deliveries": trip_dels,
            "stop_remaining_s": 0.0,
            "fuel_used_l": 0.0,
            "total_idle_s": 0,
            "anomaly_active": None,
        })

    def _segment_length_km(self, route: Route, seg_index: int, current: GeoPoint) -> float:
        return current.distance_km(route.waypoints[seg_index + 1])

    def _finish_trip(self, vehicle_id: str) -> None:
        st = self._state[vehicle_id]

    # ------------------------------------------------------------- event gen
    def _emit_telemetry(self, vehicle_id: str, speed_kmh: float,
                        idle_s: float) -> dict[str, Any]:
        st = self._state[vehicle_id]
        v: Vehicle = st["vehicle"]
        self._event_counter += 1
        weather = st["weather"]

        engine_load = _clamp(15.0 + speed_kmh * 0.85 + self.rng.uniform(-5, 5), 5.0, 99.0)
        engine_temp = 88.0 + speed_kmh * 0.06 + self.rng.uniform(-1.5, 1.5)
        engine_temp += 3.0 if weather == Weather.RAIN else (6.0 if weather == Weather.STORM else 0.0)
        if v.anomaly_profile == AnomalyKind.TEMP_DRIFT and self._is_anomaly_active(vehicle_id):
            engine_temp += self.rng.uniform(9.0, 18.0)
        if v.anomaly_profile == AnomalyKind.ENGINE_OVERLOAD and self._is_anomaly_active(vehicle_id):
            engine_load = _clamp(engine_load + self.rng.uniform(18, 35), 0.0, 100.0)
        if v.anomaly_profile == AnomalyKind.SPEED_SENSOR_NOISE and self._is_anomaly_active(vehicle_id):
            speed_kmh = _clamp(speed_kmh + self.rng.uniform(-14, 14), 0.0, 140.0)

        ambient = 18.0 + 7.0 * math.sin((self.now.hour - 8) / 24.0 * 2 * math.pi) \
            + self.rng.uniform(-1.0, 1.0)
        ambient -= 6.0 if weather == Weather.RAIN else (10.0 if weather == Weather.STORM else 0.0)

        fuel_rate = self._fuel_rate_lph(v, speed_kmh, idle_s)
        st["fuel_used_l"] += fuel_rate * (self.dt_seconds / 3600.0)
        st["fuel_level_pct"] = _clamp(
            st["fuel_level_pct"] - fuel_rate * self.dt_seconds / 3600.0 / 1.2, 0.0, 100.0)
        st["mileage_km"] += speed_kmh * self.dt_seconds / 3600.0
        st["total_idle_s"] += idle_s

        return {
            "event_id": f"tele-{self._event_counter:012d}",
            "vehicle_id": vehicle_id,
            "driver_id": self.drivers[vehicle_id].driver_id,
            "route_id": st["route_id"],
            "timestamp": self.now.isoformat().replace("+00:00", "Z"),
            "speed_kmh": round(speed_kmh, 2),
            "fuel_rate_lph": round(fuel_rate, 3),
            "fuel_level_pct": round(st["fuel_level_pct"], 2),
            "engine_load_pct": round(engine_load, 2),
            "engine_temp_c": round(engine_temp, 2),
            "ambient_temp_c": round(ambient, 2),
            "mileage_km": round(st["mileage_km"], 2),
            "idle_time_s": round(idle_s, 1),
            "weather": weather.value,
            "traffic_multiplier": round(st["traffic"], 3),
            "event_type": "telemetry",
        }

    def _emit_gps(self, vehicle_id: str) -> dict[str, Any]:
        st = self._state[vehicle_id]
        self._event_counter += 1
        lat = st["position"].latitude + self.rng.gauss(0, 0.00008)
        lon = st["position"].longitude + self.rng.gauss(0, 0.00008)
        return {
            "event_id": f"gps-{self._event_counter:012d}",
            "vehicle_id": vehicle_id,
            "route_id": st["route_id"],
            "timestamp": self.now.isoformat().replace("+00:00", "Z"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "accuracy_m": round(abs(self.rng.gauss(5.0, 2.0)), 1),
            "event_type": "gps",
        }

    def _emit_delivery(self, delivery: Delivery, status: DeliveryStatus) -> dict[str, Any]:
        st = self._state[delivery.vehicle_id] if delivery.vehicle_id else None
        self._event_counter += 1
        return {
            "event_id": f"del-{self._event_counter:012d}",
            "delivery_id": delivery.delivery_id,
            "vehicle_id": delivery.vehicle_id,
            "route_id": delivery.route_id,
            "stop_index": delivery.stop_index,
            "timestamp": self.now.isoformat().replace("+00:00", "Z"),
            "status": status.value,
            "planned_arrival_time": delivery.planned_arrival_time,
            "parcels": delivery.parcels,
            "weather": (st["weather"].value if st else "clear"),
            "event_type": "delivery",
        }

    # ------------------------------------------------------------------ tick
    def step(self) -> Iterator[dict[str, Any]]:
        """Advance one sim tick and yield all events produced during it."""
        if self.now >= self.end_time:
            return
        self.now += timedelta(seconds=self.dt_seconds)
        weather = self._weather_for(self.now)
        for v in self.vehicles:
            vid = v.vehicle_id
            st = self._state[vid]
            st["weather"] = weather
            st["traffic"] = 1.0

            if st["status"] == "IDLE":
                self._assign_trip(vid)
                if st["status"] == "IDLE":
                    continue

            st["traffic"] = self._traffic_multiplier(self.now, st["route"].congestion_factor)
            self._maybe_trigger_anomaly(vid)

            if st["status"] == "STOPPED":
                # completing a delivery stop
                remaining = st["stop_remaining_s"] - self.dt_seconds
                if remaining > 0:
                    st["stop_remaining_s"] = remaining
                    yield self._emit_telemetry(vid, 0.0, self.dt_seconds)
                    yield self._emit_gps(vid)
                    continue
                st["status"] = "DRIVING"
                st["stop_remaining_s"] = 0.0
                st["leg_start_distance"] = st["distance_from_start"]

            # driving
            speed = self._cruise_speed(v, self.now, weather, st["traffic"])
            idle_s = 0.0
            if speed < 6.0 or (st["traffic"] > 1.4 and self.rng.random() < LIGHT_IDLE_PROB):
                # congested crawl / traffic light
                speed = self.rng.uniform(0.0, 4.0)
                idle_s = float(self.dt_seconds)
            dist_km = speed * self.dt_seconds / 3600.0
            st["distance_from_start"] += dist_km

            # move position along current segment
            seg_remaining = st["seg_remaining_km"] - dist_km
            if seg_remaining <= 0 and st["seg_index"] < len(st["route"].waypoints) - 2:
                st["seg_index"] += 1
                st["position"] = st["route"].waypoints[st["seg_index"]]
                st["seg_remaining_km"] = st["position"].distance_km(
                    st["route"].waypoints[st["seg_index"] + 1]) + seg_remaining
            elif seg_remaining <= 0:
                st["position"] = st["route"].waypoints[-1]
                st["seg_remaining_km"] = 0.0
            else:
                st["seg_remaining_km"] = seg_remaining
                # interpolate position along segment
                a = st["route"].waypoints[st["seg_index"]]
                b = st["route"].waypoints[st["seg_index"] + 1]
                frac = 1.0 - st["seg_remaining_km"] / max(0.001, a.distance_km(b))
                frac = _clamp(frac, 0.0, 1.0)
                st["position"] = GeoPoint(
                    a.latitude + (b.latitude - a.latitude) * frac,
                    a.longitude + (b.longitude - a.longitude) * frac)

            # delivery stops: check arrival at next stop fraction
            nd = st["next_delivery_idx"]
            if nd < len(st["trip_deliveries"]):
                d = st["trip_deliveries"][nd]
                route_len = st["route"].distance_km
                stop_dist = d.stop_fraction * route_len
                if st["distance_from_start"] >= stop_dist:
                    if d.planned_dispatch_time is None:
                        d.planned_dispatch_time = self.now.isoformat().replace("+00:00", "Z")
                        # planned arrival uses the route's TYPICAL speed, not the
                        # actual (weather/traffic affected) speed, so that real
                        # delays can materialise when conditions are bad.
                        remaining_km = max(0.0, stop_dist - st["distance_from_start"])
                        typical_min = st["route"].typical_duration_min
                        typical_speed = route_len / max(1e-6, typical_min) * 60.0  # km/h
                        planned_min = remaining_km / max(1.0, typical_speed) * 60.0
                        d.planned_arrival_time = (
                            self.now + timedelta(minutes=planned_min)).isoformat().replace("+00:00", "Z")
                        yield self._emit_delivery(d, DeliveryStatus.OUT_FOR_DELIVERY)
                    planned = datetime.fromisoformat(d.planned_arrival_time.replace("Z", "+00:00"))
                    late_min = (self.now - planned).total_seconds() / 60.0
                    d.actual_arrival_time = self.now.isoformat().replace("+00:00", "Z")
                    d.leg_distance_km = round(st["distance_from_start"] - st["leg_start_distance"], 2)
                    d.duration_minutes = round(
                        (self.now - st["trip_started_at"]).total_seconds() / 60.0, 2)
                    d.weather = weather
                    d.traffic_multiplier = round(st["traffic"], 3)
                    if late_min > 10:
                        d.status = DeliveryStatus.DELAYED
                        d.delayed = True
                    elif late_min < -30 and self.rng.random() < 0.03:
                        d.status = DeliveryStatus.FAILED
                        d.delayed = False
                    else:
                        d.status = DeliveryStatus.DELIVERED
                        d.delayed = False
                    yield self._emit_delivery(d, d.status)
                    st["next_delivery_idx"] += 1
                    stop_min = self.rng.uniform(*STOP_IDLE_MINUTES)
                    if weather == Weather.STORM:
                        stop_min *= 1.4
                    st["status"] = "STOPPED"
                    st["stop_remaining_s"] = stop_min * 60.0
                    yield self._emit_telemetry(vid, 0.0, self.dt_seconds)
                    yield self._emit_gps(vid)
                    continue

            # end of route
            if st["seg_remaining_km"] <= 0 and st["next_delivery_idx"] >= len(st["trip_deliveries"]):
                self._finish_trip(vid)
                continue

            yield self._emit_telemetry(vid, speed, idle_s)
            yield self._emit_gps(vid)

    def run(self, max_events: int | None = None) -> Iterator[dict[str, Any]]:
        """Run the simulation until the end time or the event cap is reached."""
        cap = max_events if max_events is not None else float("inf")
        while self.now < self.end_time and self._event_counter < cap:
            for event in self.step():
                if self._event_counter > cap:
                    return
                yield event

# ---------------------------------------------------------------------------
# Population factories (deterministic given a seed)
# ---------------------------------------------------------------------------
def make_hubs(seed: int) -> list[Hub]:
    rng = random.Random(seed)
    hubs = []
    for i, name in enumerate(HUB_NAMES):
        angle = 2 * math.pi * i / len(HUB_NAMES)
        radius = REGION_RADIUS_DEG * rng.uniform(0.25, 1.0)
        lat = REGION_CENTER_LAT + radius * math.cos(angle) * 0.72
        lon = REGION_CENTER_LON + radius * math.sin(angle) * 1.05
        hubs.append(Hub(hub_id=f"H{i + 1:02d}", name=name,
                        location=GeoPoint(round(lat, 6), round(lon, 6))))
    return hubs


def make_vehicles(seed: int, count: int) -> tuple[list[Vehicle], list[Driver]]:
    rng = random.Random(seed)
    vehicles, drivers = [], []
    type_pool = ([VehicleType.VAN] * 40 + [VehicleType.BOX_TRUCK] * 30
                 + [VehicleType.SEMI_TRAILER] * 20 + [VehicleType.REFRIGERATED] * 10)
    for i in range(count):
        vtype = rng.choice(type_pool)
        age = round(rng.uniform(0.5, 12.0), 1)
        base_risk = rng.uniform(0.01, 0.06)
        risk = min(0.9, base_risk * (1 + 0.35 * age))
        profile = rng.choice(ANOMALY_PROFILES) if rng.random() < 0.55 else AnomalyKind.NONE
        vehicle = Vehicle(
            vehicle_id=f"V{i + 1:05d}",
            vehicle_type=vtype,
            age_years=age,
            base_speed_kmh=VEHICLE_TYPE_PARAMS[vtype]["cruise"],
            fuel_efficiency=VEHICLE_TYPE_PARAMS[vtype]["fuel_curve_a"] * 10
            + VEHICLE_TYPE_PARAMS[vtype]["fuel_curve_b"] * 6400,
            anomaly_profile=profile,
            anomaly_risk=risk,
        )
        driver = Driver(
            driver_id=f"D{i + 1:05d}",
            vehicle_id=vehicle.vehicle_id,
            shift_start_hour=rng.choice([5, 6, 7, 8]),
            shift_duration_hours=rng.choice([8, 9, 10, 12]),
            behavior=rng.choices(["cautious", "normal", "aggressive"],
                                 weights=[25, 60, 15])[0],
        )
        vehicles.append(vehicle)
        drivers.append(driver)
    return vehicles, drivers


def make_routes(seed: int, hubs: list[Hub], count: int = 120) -> list[Route]:
    rng = random.Random(seed + 1)
    routes = []
    for i in range(count):
        origin = rng.choice(hubs)
        dest = rng.choice([h for h in hubs if h.hub_id != origin.hub_id])
        n_mid = rng.randint(1, 3)
        waypoints = [origin.location]
        for _ in range(n_mid):
            a = rng.choice(hubs).location
            waypoints.append(GeoPoint(
                round((waypoints[-1].latitude + a.latitude) / 2 + rng.uniform(-0.05, 0.05), 6),
                round((waypoints[-1].longitude + a.longitude) / 2 + rng.uniform(-0.05, 0.05), 6)))
        waypoints.append(dest.location)
        dist = sum(a.distance_km(b) for a, b in zip(waypoints, waypoints[1:]))
        congestion = round(min(2.5, max(0.5, rng.lognormvariate(0.0, 0.45))), 2)
        avg_speed = 55.0 / congestion
        routes.append(Route(
            route_id=f"R{i + 1:03d}",
            origin_hub_id=origin.hub_id,
            destination_hub_id=dest.hub_id,
            waypoints=waypoints,
            distance_km=round(dist, 2),
            congestion_factor=congestion,
            typical_duration_min=round(dist / avg_speed * 60.0, 1),
        ))
    return routes


def make_deliveries(seed: int, routes: list[Route], per_route: int = 40) -> list[Delivery]:
    rng = random.Random(seed + 2)
    deliveries = []
    counter = 0
    for route in routes:
        for _ in range(per_route):
            counter += 1
            deliveries.append(Delivery(
                delivery_id=f"DLV-{counter:06d}",
                route_id=route.route_id,
                stop_index=counter % 9,
                stop_fraction=round(rng.uniform(0.15, 0.98), 3),
                parcels=rng.randint(2, 60),
            ))
    return deliveries





