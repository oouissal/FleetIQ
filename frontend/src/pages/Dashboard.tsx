import { useQuery } from '@tanstack/react-query';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '../api/client';
import KpiCard from '../components/KpiCard';

const fmt = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? '—' : v.toFixed(digits);

const STATUS_COLORS: Record<string, string> = {
  DELIVERED: '#10b981',
  DELAYED: '#f59e0b',
  FAILED: '#ef4444',
  OUT_FOR_DELIVERY: '#0ea5e9',
};

export default function Dashboard() {
  const kpis = useQuery({ queryKey: ['kpis'], queryFn: api.kpis });
  const series = useQuery({ queryKey: ['kpiSeries'], queryFn: () => api.kpiSeries(288) });
  const summary = useQuery({ queryKey: ['fleetSummary'], queryFn: api.fleetSummary });
  const deliveries = useQuery({
    queryKey: ['deliveriesDashboard'],
    queryFn: () => api.deliveries({ limit: 1000 }),
  });
  const routes = useQuery({ queryKey: ['routesDashboard'], queryFn: () => api.routes(15) });
  const anomalies = useQuery({
    queryKey: ['anomaliesDashboard'],
    queryFn: () => api.anomalies({ limit: 500 }),
  });

  const k = kpis.data;
  const deliveryStatus = (deliveries.data?.deliveries ?? []).reduce<Record<string, number>>(
    (acc, d) => {
      acc[d.status] = (acc[d.status] ?? 0) + 1;
      return acc;
    },
    {},
  );
  const deliveryPie = Object.entries(deliveryStatus).map(([name, value]) => ({ name, value }));

  const anomaliesByHour = (anomalies.data?.anomalies ?? []).reduce<Record<string, number>>(
    (acc, a) => {
      const hour = a.timestamp ? String(a.timestamp).slice(0, 13) : 'unknown';
      acc[hour] = (acc[hour] ?? 0) + 1;
      return acc;
    },
    {},
  );
  const anomalySeries = Object.entries(anomaliesByHour)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([hour, count]) => ({ hour, count }));

  const routeBars = (routes.data?.routes ?? []).map((r) => ({
    route: r.route_id,
    speed: r.avg_speed_kmh ?? 0,
    fuel: r.avg_fuel_per_100km ?? 0,
  }));

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <KpiCard label="Active Vehicles" value={k?.active_vehicles ?? '—'} />
        <KpiCard
          label="Deliveries"
          value={k?.total_deliveries ?? '—'}
          sub={`${summary.data?.vehicles_total ?? '—'} vehicles in fleet`}
        />
        <KpiCard
          label="On-Time Rate"
          value={
            k?.on_time_rate !== null && k?.on_time_rate !== undefined
              ? `${(k.on_time_rate * 100).toFixed(1)}%`
              : '—'
          }
        />
        <KpiCard label="Avg ETA" value="—" sub="see Predictions page" />
        <KpiCard label="Detected Anomalies" value={k?.detected_anomalies ?? '—'} />
        <KpiCard label="Avg Fuel (l/h)" value={fmt(k?.avg_fuel_rate_lph, 2)} />
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Fleet activity (5-min windows)</h2>
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={series.data?.series ?? []}>
            <defs>
              <linearGradient id="av" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b6cf0" stopOpacity={0.8} />
                <stop offset="95%" stopColor="#3b6cf0" stopOpacity={0.1} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="window_start" tick={{ fontSize: 10 }} minTickGap={40} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Area
              type="monotone"
              dataKey="active_vehicles"
              stroke="#3b6cf0"
              fill="url(#av)"
              name="active vehicles"
            />
          </AreaChart>
        </ResponsiveContainer>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Delivery status</h2>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={deliveryPie}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={85}
              >
                {deliveryPie.map((entry) => (
                  <Cell key={entry.name} fill={STATUS_COLORS[entry.name] ?? '#94a3b8'} />
                ))}
              </Pie>
              <Legend />
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Anomalies over time</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={anomalySeries}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="hour" tick={{ fontSize: 10 }} minTickGap={40} />
              <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#ef4444" name="anomalies" />
            </LineChart>
          </ResponsiveContainer>
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          Route performance (top 15 by avg speed)
        </h2>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={routeBars}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="route" tick={{ fontSize: 10 }} />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
            <Tooltip />
            <Legend />
            <Bar yAxisId="left" dataKey="speed" fill="#3b6cf0" name="avg speed km/h" />
            <Bar yAxisId="right" dataKey="fuel" fill="#10b981" name="fuel l/100km" />
          </BarChart>
        </ResponsiveContainer>
      </section>
    </div>
  );
}
