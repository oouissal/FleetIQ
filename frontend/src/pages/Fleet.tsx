import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import StatusBadge from '../components/StatusBadge';

const PAGE_SIZE = 25;

export default function Fleet() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [sortBy, setSortBy] = useState('vehicle_id');
  const [order, setOrder] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(0);

  const vehicles = useQuery({
    queryKey: ['vehicles', search, statusFilter, typeFilter, sortBy, order, page],
    queryFn: () =>
      api.vehicles({
        search: search || undefined,
        status: statusFilter || undefined,
        vehicle_type: typeFilter || undefined,
        sort_by: sortBy,
        order,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
  });

  const columns = useMemo(
    () => [
      { key: 'vehicle_id', label: 'Vehicle ID' },
      { key: 'status', label: 'Status' },
      { key: 'vehicle_type', label: 'Type' },
      { key: 'speed_kmh', label: 'Speed (km/h)' },
      { key: 'fuel_rate_lph', label: 'Fuel (l/h)' },
      { key: 'route_id', label: 'Route' },
      { key: 'engine_temp_c', label: 'Temp (°C)' },
      { key: 'last_seen', label: 'Last seen' },
    ],
    [],
  );

  const toggleSort = (key: string) => {
    if (sortBy === key) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(key);
      setOrder('asc');
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
          placeholder="Search vehicle id…"
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(0);
          }}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
        <select
          value={typeFilter}
          onChange={(e) => {
            setTypeFilter(e.target.value);
            setPage(0);
          }}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
        >
          <option value="">All types</option>
          <option value="VAN">VAN</option>
          <option value="BOX_TRUCK">BOX_TRUCK</option>
          <option value="SEMI_TRAILER">SEMI_TRAILER</option>
          <option value="REFRIGERATED">REFRIGERATED</option>
        </select>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  className="cursor-pointer px-3 py-2 hover:text-brand-600"
                  onClick={() => toggleSort(c.key)}
                >
                  {c.label}
                  {sortBy === c.key ? (order === 'asc' ? ' ↑' : ' ↓') : ''}
                </th>
              ))}
              <th className="px-3 py-2">Location</th>
            </tr>
          </thead>
          <tbody>
            {(vehicles.data ?? []).map((v) => (
              <tr key={v.vehicle_id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-3 py-2 font-medium">
                  <Link to={`/fleet/${v.vehicle_id}`} className="text-brand-600 hover:underline">
                    {v.vehicle_id}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <StatusBadge status={v.status} />
                </td>
                <td className="px-3 py-2">{v.vehicle_type ?? '—'}</td>
                <td className="px-3 py-2">{v.speed_kmh ?? '—'}</td>
                <td className="px-3 py-2">{v.fuel_rate_lph ?? '—'}</td>
                <td className="px-3 py-2">{v.route_id ?? '—'}</td>
                <td className="px-3 py-2">{v.engine_temp_c ?? '—'}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{v.last_seen ?? '—'}</td>
                <td className="px-3 py-2 text-xs text-slate-500">
                  {v.latitude !== null && v.longitude !== null
                    ? `${v.latitude.toFixed(3)}, ${v.longitude.toFixed(3)}`
                    : '—'}
                </td>
              </tr>
            ))}
            {!vehicles.isLoading && (vehicles.data ?? []).length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-slate-400">
                  No vehicles match — or no gold data is available yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <button
          disabled={page === 0}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
        >
          ← Previous
        </button>
        <span className="text-sm text-slate-500">Page {page + 1}</span>
        <button
          disabled={(vehicles.data ?? []).length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
