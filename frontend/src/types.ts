export interface KpiResponse {
  active_vehicles: number;
  total_deliveries: number;
  on_time_rate: number | null;
  avg_duration_minutes: number | null;
  detected_anomalies: number;
  avg_fuel_rate_lph: number | null;
  window_start: string | null;
  note: string;
}

export interface VehicleCard {
  vehicle_id: string;
  status: string;
  vehicle_type: string | null;
  latitude: number | null;
  longitude: number | null;
  speed_kmh: number | null;
  fuel_rate_lph: number | null;
  fuel_level_pct: number | null;
  route_id: string | null;
  last_seen: string | null;
  engine_temp_c: number | null;
  age_years: number | null;
}

export interface FleetSummary {
  vehicles_total: number;
  vehicles_active: number;
  vehicles_inactive: number;
  detected_anomalies: number;
  vehicle_types: Record<string, number>;
  note?: string;
}

export interface VehicleDetail {
  vehicle_id: string;
  current: Record<string, unknown>;
  history_speed: { t: string; speed_kmh: number }[];
  history_fuel: { t: string; fuel_rate_lph: number }[];
  history_idle: { t: string; idle_time_s: number }[];
  anomaly_score: number | null;
  note: string;
}

export interface RouteInfo {
  route_id: string;
  avg_speed_kmh: number | null;
  avg_traffic_multiplier: number | null;
  avg_fuel_per_100km: number | null;
  total_distance_km: number | null;
  distance_km: number | null;
  congestion_factor: number | null;
  typical_duration_min: number | null;
  windows?: number;
}

export interface RoutesResponse {
  routes: RouteInfo[];
  note?: string;
}

export interface DeliveryInfo {
  delivery_id: string;
  vehicle_id: string | null;
  route_id: string | null;
  status: string;
  planned_arrival_time: string | null;
  actual_arrival_time: string | null;
  duration_minutes: number | null;
  delayed: boolean | null;
  weather: string | null;
}

export interface DeliveriesResponse {
  deliveries: DeliveryInfo[];
  total: number;
  note?: string;
}

export interface AnomalyItem {
  vehicle_id: string | null;
  timestamp: string | null;
  anomaly_score: number | null;
  pattern: string[];
  description: string;
  signals: Record<string, number | null>;
}

export interface AnomaliesResponse {
  anomalies: AnomalyItem[];
  count: number;
  note?: string;
}

export interface EtaModelInfo {
  model_name: string;
  model_type: string;
  metrics: { mae: number; rmse: number; r2: number } | null;
  interval_half_width_min: number | null;
  run_id: string | null;
  dataset_rows: number | null;
  registry_version: string | null;
  baseline_metrics: { mae: number; rmse: number; r2: number } | null;
  selection?: string;
}

export interface AnomalyModelInfo {
  model_name: string;
  method: string;
  contamination: number | null;
  n_events: number | null;
  n_flagged: number | null;
  flagged_share: number | null;
  features: string[] | null;
  limitations: string[];
}

export interface ModelInfoResponse {
  eta_model: EtaModelInfo | null;
  anomaly_model: AnomalyModelInfo | null;
  available: boolean;
  note: string;
}

export interface EtaPrediction {
  predicted_eta_minutes: number;
  interval: {
    method: string;
    description: string;
    lower_minutes: number;
    upper_minutes: number;
  };
  model_version: string | null;
  model_run_id: string | null;
  prediction_timestamp: string;
  features_used: Record<string, number>;
}

export interface AnomalyPrediction {
  anomaly_score: number;
  anomaly_flag: boolean;
  description: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  data_available: boolean;
  models_available: boolean;
}
