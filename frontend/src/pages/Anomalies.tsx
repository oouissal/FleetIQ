import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

function severity(score: number | null): { label: string; cls: string } {
  if (score === null) return { label: 'unknown', cls: 'bg-slate-100 text-slate-600' };
  if (score > 0.25) return { label: 'high', cls: 'bg-red-100 text-red-800' };
  if (score > 0.15) return { label: 'medium', cls: 'bg-amber-100 text-amber-800' };
  return { label: 'low', cls: 'bg-yellow-50 text-yellow-800' };
}

export default function Anomalies() {
  const anomalies = useQuery({
    queryKey: ['anomaliesPage'],
    queryFn: () => api.anomalies({ limit: 300 }),
  });
  const list = anomalies.data?.anomalies ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs uppercase text-slate-500">Anomaly count</p>
          <p className="text-2xl font-bold">{anomalies.data?.count ?? '—'}</p>
        </div>
        <p className="max-w-xl text-xs text-slate-500">
          Unsupervised Isolation Forest detections. A flag means &ldquo;unusual telemetry
          pattern detected&rdquo; relative to the fleet distribution — it is NOT a diagnosed
          fault. Pattern names describe the deviating measurements only.
        </p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Vehicle</th>
              <th className="px-3 py-2">Timestamp</th>
              <th className="px-3 py-2">Score</th>
              <th className="px-3 py-2">Severity</th>
              <th className="px-3 py-2">Pattern</th>
              <th className="px-3 py-2">Contributing signals</th>
            </tr>
          </thead>
          <tbody>
            {list.map((a, i) => {
              const sev = severity(a.anomaly_score);
              return (
                <tr key={`${a.vehicle_id}-${a.timestamp}-${i}`} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium">{a.vehicle_id ?? '—'}</td>
                  <td className="px-3 py-2 text-xs">{a.timestamp ?? '—'}</td>
                  <td className="px-3 py-2">{a.anomaly_score?.toFixed(3) ?? '—'}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${sev.cls}`}>
                      {sev.label}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {a.pattern.length > 0
                      ? a.pattern.map((p) => (
                          <span
                            key={p}
                            className="mr-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-xs"
                          >
                            {p}
                          </span>
                        ))
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {Object.entries(a.signals)
                      .filter(([, v]) => v !== null)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(', ')}
                  </td>
                </tr>
              );
            })}
            {list.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-slate-400">
                  No flagged anomalies in the current data.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
