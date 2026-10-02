const styles: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-800',
  inactive: 'bg-slate-100 text-slate-600',
  DELIVERED: 'bg-emerald-100 text-emerald-800',
  DELAYED: 'bg-amber-100 text-amber-800',
  FAILED: 'bg-red-100 text-red-800',
  OUT_FOR_DELIVERY: 'bg-sky-100 text-sky-800',
  temp_alert: 'bg-red-100 text-red-800',
  engine_load_alert: 'bg-orange-100 text-orange-800',
  excess_idle: 'bg-yellow-100 text-yellow-800',
  ok: 'bg-emerald-100 text-emerald-800',
};

export default function StatusBadge({ status }: { status: string }) {
  const cls = styles[status] ?? 'bg-slate-100 text-slate-700';
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {status}
    </span>
  );
}
