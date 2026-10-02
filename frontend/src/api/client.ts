import axios from 'axios';
import type {
  AnomaliesResponse,
  AnomalyPrediction,
  DeliveriesResponse,
  EtaPrediction,
  FleetSummary,
  HealthResponse,
  KpiResponse,
  ModelInfoResponse,
  RoutesResponse,
  VehicleCard,
  VehicleDetail,
} from '../types';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/',
  timeout: 30000,
});

export const api = {
  health: async () => (await client.get<HealthResponse>('/health')).data,
  kpis: async () => (await client.get<KpiResponse>('/api/kpis')).data,
  kpiSeries: async (limit = 288) =>
    (await client.get<{ series: Record<string, number | string>[] }>('/api/kpis/series', { params: { limit } })).data,
  fleetSummary: async () => (await client.get<FleetSummary>('/api/fleet/summary')).data,
  vehicles: async (params: {
    search?: string;
    status?: string;
    vehicle_type?: string;
    sort_by?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) => (await client.get<VehicleCard[]>('/api/fleet/vehicles', { params })).data,
  vehicleDetail: async (id: string) =>
    (await client.get<VehicleDetail>(`/api/fleet/vehicles/${id}`)).data,
  routes: async (limit = 100) => (await client.get<RoutesResponse>('/api/routes', { params: { limit } })).data,
  deliveries: async (params: { status?: string; route_id?: string; limit?: number }) =>
    (await client.get<DeliveriesResponse>('/api/deliveries', { params })).data,
  anomalies: async (params: { limit?: number; vehicle_id?: string; min_score?: number }) =>
    (await client.get<AnomaliesResponse>('/api/anomalies', { params })).data,
  modelInfo: async () => (await client.get<ModelInfoResponse>('/api/model/info')).data,
  predictEta: async (payload: Record<string, unknown>) =>
    (await client.post<EtaPrediction>('/api/predict/eta', payload)).data,
  predictAnomaly: async (observations: Record<string, number>[]) =>
    (await client.post<AnomalyPrediction[]>('/api/predict/anomaly', { observations })).data,
};

export default client;
