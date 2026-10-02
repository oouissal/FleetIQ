import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import StatusBadge from '../components/StatusBadge';

const STATUSES = ['', 'DELIVERED', 'DELAYED', 'FAILED'];

export default function Deliveries() {
  const [status, setStatus] = useState('');
  const deliveries = useQuery({
    queryKey: ['deliveries', status],
    queryFn: () => api.deliveries({ status: status || undefined, limit: 200 }),
  });
  const list = deliveries.data?.deliveries ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <label className="text-sm text-slate-600">Status:</label>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s || 'All'}
            </option>
          ))}
        </select>
        <span className="text-sm text-slate-500">
          {deliveries.data?.total ?? 0} matching deliveries
        </span>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Delivery</th>
              <th className="px-3 py-2">Vehicle</th>
              <th className="px-3 py-2">Route</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Planned arrival</th>
              <th className="px-3 py-2">Actual arrival</th>
              <th className="px-3 py-2">Duration (min)</th>
              <th className="px-3 py-2">Weather</th>
            </tr>
          </thead>
          <tbody>
            {list.map((d) => (
              <tr key={d.delivery_id} className="border-t border-slate-100">
                <td className="px-3 py-2 font-medium">{d.delivery_id}</td>
                <td className="px-3 py-2">{d.vehicle_id ?? '—'}</td>
                <td className="px-3 py-2">{d.route_id ?? '—'}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={d.status} />
                </td>
                <td className="px-3 py-2 text-xs">{d.planned_arrival_time ?? '—'}</td>
                <td className="px-3 py-2 text-xs">{d.actual_arrival_time ?? '—'}</td>
                <td className="px-3 py-2">{d.duration_minutes ?? '—'}</td>
                <td className="px-3 py-2">{d.weather ?? '—'}</td>
              </tr>
            ))}
            {list.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-slate-400">
                  No deliveries match.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
