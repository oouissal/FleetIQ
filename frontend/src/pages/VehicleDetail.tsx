import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '../api/client';
import StatusBadge from '../components/StatusBadge';

export default function VehicleDetail() {
  const { vehicleId = '' } = useParams();
  const detail = useQuery({
    queryKey: ['vehicleDetail', vehicleId],
    queryFn: () => api.vehicleDetail(vehicleId),
    enabled: !!vehicleId,
  });

  const d = detail.data;
  const current = (d?.current ?? {}) as Record<string, string | number | null | undefined>;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">{vehicleId}</h2>
        <Link to="/fleet" className="text-sm text-brand-600 hover:underline">
          ← back to fleet
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ['Status', current.status ? <StatusBadge status={String(current.status)} /> : '—'],
          ['Type', current.vehicle_type ?? '—'],
          ['Speed (km/h)', current.speed_kmh ?? '—'],
          ['Fuel rate (l/h)', current.fuel_rate_lph ?? '—'],
          ['Fuel level (%)', current.fuel_level_pct ?? '—'],
          ['Route', current.route_id ?? '—'],
          ['Engine temp (°C)', current.engine_temp_c ?? '—'],
          ['Anomaly score', d?.anomaly_score !== null && d?.anomaly_score !== undefined
            ? Number(d.anomaly_score).toFixed(2) : '—'],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-xs text-slate-500">{label}</p>
            <p className="mt-1 font-semibold">{value}</p>
          </div>
        ))}
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="mb-2 text-sm font-semibold text-slate-700">Historical speed (last 500 events)</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={d?.history_speed ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={60} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Line type="monotone" dataKey="speed_kmh" stroke="#3b6cf0" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">Fuel consumption (l/h)</h3>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={d?.history_fuel ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={60} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Line type="monotone" dataKey="fuel_rate_lph" stroke="#10b981" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">Idle time (s per tick)</h3>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={d?.history_idle ?? []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} minTickGap={60} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Line type="monotone" dataKey="idle_time_s" stroke="#f59e0b" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </section>
      </div>
      <p className="text-xs text-slate-400">{d?.note}</p>
    </div>
  );
}
