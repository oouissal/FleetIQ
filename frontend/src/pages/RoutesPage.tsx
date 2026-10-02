import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? '—' : v.toFixed(d);

export default function RoutesPage() {
  const routes = useQuery({ queryKey: ['routes'], queryFn: () => api.routes(120) });
  const list = routes.data?.routes ?? [];

  const worst = [...list]
    .sort((a, b) => (a.avg_speed_kmh ?? 999) - (b.avg_speed_kmh ?? 999))
    .slice(0, 5);

  return (
    <div className="space-y-5">
      {worst.length > 0 ? (
        <section className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <h2 className="text-sm font-semibold text-amber-800">
            Routes with the lowest average speed (last windows)
          </h2>
          <ul className="mt-2 grid gap-2 md:grid-cols-3">
            {worst.map((r) => (
              <li key={r.route_id} className="rounded-lg bg-white p-3 text-sm shadow-sm">
                <span className="font-semibold">{r.route_id}</span>
                <span className="ml-2 text-slate-600">{fmt(r.avg_speed_kmh, 1)} km/h</span>
                <span className="ml-2 text-slate-400">
                  traffic ×{fmt(r.avg_traffic_multiplier, 2)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Route</th>
              <th className="px-3 py-2">Avg speed (km/h)</th>
              <th className="px-3 py-2">Avg traffic ×</th>
              <th className="px-3 py-2">Fuel (l/100km)</th>
              <th className="px-3 py-2">Distance (km)</th>
              <th className="px-3 py-2">Route length (km)</th>
              <th className="px-3 py-2">Typical duration (min)</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r) => (
              <tr key={r.route_id} className="border-t border-slate-100">
                <td className="px-3 py-2 font-medium">{r.route_id}</td>
                <td className="px-3 py-2">{fmt(r.avg_speed_kmh, 1)}</td>
                <td className="px-3 py-2">{fmt(r.avg_traffic_multiplier, 2)}</td>
                <td className="px-3 py-2">{fmt(r.avg_fuel_per_100km, 1)}</td>
                <td className="px-3 py-2">{fmt(r.total_distance_km, 1)}</td>
                <td className="px-3 py-2">{fmt(r.distance_km, 1)}</td>
                <td className="px-3 py-2">{fmt(r.typical_duration_min, 0)}</td>
              </tr>
            ))}
            {list.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-slate-400">
                  No route data available yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
