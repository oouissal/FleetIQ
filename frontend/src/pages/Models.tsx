import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

const fmt = (v: number | null | undefined, d = 3) =>
  v === null || v === undefined ? '—' : v.toFixed(d);

export default function Models() {
  const info = useQuery({ queryKey: ['modelInfo'], queryFn: api.modelInfo });
  const eta = info.data?.eta_model;
  const anomaly = info.data?.anomaly_model;

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold">ETA Model</h2>
        {eta ? (
          <div className="mt-3 grid gap-4 md:grid-cols-3">
            <div>
              <p className="text-xs uppercase text-slate-500">Model type</p>
              <p className="font-semibold">{eta.model_type}</p>
              <p className="mt-1 text-xs text-slate-400">version {eta.registry_version ?? '—'}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-slate-500">Metrics (future test set)</p>
              <table className="mt-1 text-sm">
                <tbody>
                  <tr>
                    <td className="pr-3 text-slate-500">MAE</td>
                    <td className="font-semibold">{fmt(eta.metrics?.mae, 2)} min</td>
                  </tr>
                  <tr>
                    <td className="pr-3 text-slate-500">RMSE</td>
                    <td className="font-semibold">{fmt(eta.metrics?.rmse, 2)} min</td>
                  </tr>
                  <tr>
                    <td className="pr-3 text-slate-500">R²</td>
                    <td className="font-semibold">{fmt(eta.metrics?.r2)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="text-sm">
              <p className="text-xs uppercase text-slate-500">MLflow run</p>
              <p className="break-all font-mono text-xs">{eta.run_id ?? '—'}</p>
              <p className="mt-2 text-xs text-slate-400">
                Training rows: {eta.dataset_rows ?? '—'} ·{' '}
                {eta.interval_half_width_min !== null
                  ? `interval ±${eta.interval_half_width_min} min`
                  : ''}
              </p>
              {eta.baseline_metrics ? (
                <p className="mt-1 text-xs text-slate-400">
                  Baseline (median) RMSE: {fmt(eta.baseline_metrics.rmse, 2)} min
                </p>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="mt-2 text-sm text-slate-500">
            ETA model metadata not available — run the training pipeline first
            (ml/train_eta.py).
          </p>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold">Anomaly Detection Model</h2>
        {anomaly ? (
          <div className="mt-3 grid gap-4 md:grid-cols-3">
            <div>
              <p className="text-xs uppercase text-slate-500">Method</p>
              <p className="font-semibold">{anomaly.method}</p>
              <p className="mt-1 text-xs text-slate-400">
                contamination = {anomaly.contamination}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase text-slate-500">Detected anomalies</p>
              <p className="font-semibold">
                {anomaly.n_flagged ?? '—'} / {anomaly.n_events ?? '—'}
              </p>
              <p className="text-xs text-slate-400">
                {anomaly.flagged_share !== null && anomaly.flagged_share !== undefined
                  ? `${(anomaly.flagged_share * 100).toFixed(2)}% of events flagged`
                  : ''}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase text-slate-500">Features</p>
              <p className="text-xs text-slate-500">
                {(anomaly.features ?? []).join(', ')}
              </p>
            </div>
          </div>
        ) : (
          <p className="mt-2 text-sm text-slate-500">
            Anomaly model metadata not available — run ml/train_anomaly.py first.
          </p>
        )}
        <div className="mt-4 rounded-lg bg-amber-50 p-4">
          <h3 className="text-sm font-semibold text-amber-800">Limitations</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-900">
            {(anomaly?.limitations ?? [
              'Unsupervised: unusual ≠ faulty.',
              'Patterns are not diagnosed causes.',
              'Trained on synthetic data only.',
            ]).map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
