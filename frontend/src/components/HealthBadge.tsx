import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export default function HealthBadge() {
  const { data, isError } = useQuery({ queryKey: ['health'], queryFn: api.health });
  if (isError) {
    return (
      <span className="rounded-full bg-red-600 px-3 py-1 text-xs font-semibold text-white">
        API unreachable
      </span>
    );
  }
  const ok = data?.status === 'ok';
  return (
    <span
      className={`rounded-full px-3 py-1 text-xs font-semibold ${
        ok ? 'bg-emerald-500/20 text-emerald-200' : 'bg-amber-500/20 text-amber-200'
      }`}
      title={
        data
          ? `data=${data.data_available ? 'available' : 'missing'}, models=${
              data.models_available ? 'loaded' : 'missing'
            }`
          : 'loading'
      }
    >
      {data ? (ok ? 'API OK' : 'API degraded') : '…'}
    </span>
  );
}
