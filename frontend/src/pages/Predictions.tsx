import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { AnomalyPrediction, EtaPrediction } from '../types';

const VEHICLE_TYPES = ['VAN', 'BOX_TRUCK', 'SEMI_TRAILER', 'REFRIGERATED'];

const DEFAULT_ETA_FORM = {
  origin: 'Northgate DC',
  destination: 'Riverside Hub',
  distance_km: 45,
  vehicle_type: 'BOX_TRUCK',
  dispatch_time: '',
  congestion_factor: 1.2,
  historical_route_duration_min: 55,
  weather: 'clear',
  parcels: 12,
};

const DEFAULT_TELEMETRY = {
  speed_kmh: 82,
  acceleration_kmh_s: 0.4,
  fuel_rate_lph: 11.2,
  engine_load_pct: 55,
  engine_temp_c: 92,
  ambient_temp_c: 18,
  idle_time_s: 0,
};

export default function Predictions() {
  const [etaForm, setEtaForm] = useState(DEFAULT_ETA_FORM);
  const [etaResult, setEtaResult] = useState<EtaPrediction | null>(null);
  const [telemetry, setTelemetry] = useState(DEFAULT_TELEMETRY);
  const [anomalyResult, setAnomalyResult] = useState<AnomalyPrediction[] | null>(null);

  const modelInfo = useQuery({ queryKey: ['modelInfoPredictions'], queryFn: api.modelInfo });

  const etaMutation = useMutation({
    mutationFn: () => api.predictEta(etaForm),
    onSuccess: setEtaResult,
  });

  const anomalyMutation = useMutation({
    mutationFn: () => api.predictAnomaly([telemetry]),
    onSuccess: setAnomalyResult,
  });

  const setField =
    (key: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setEtaForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold">ETA Prediction</h2>
        <div className="mt-4 grid grid-cols-2 gap-3">
          {(
            [
              ['origin', 'Origin'],
              ['destination', 'Destination'],
              ['distance_km', 'Distance (km)'],
              ['historical_route_duration_min', 'Hist. route duration (min)'],
              ['congestion_factor', 'Congestion factor'],
              ['parcels', 'Parcels'],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="text-sm">
              <span className="text-slate-500">{label}</span>
              <input
                value={etaForm[key]}
                onChange={setField(key)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
              />
            </label>
          ))}
          <label className="text-sm">
            <span className="text-slate-500">Vehicle type</span>
            <select
              value={etaForm.vehicle_type}
              onChange={setField('vehicle_type')}
              className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
            >
              {VEHICLE_TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-slate-500">Weather (simulated forecast)</span>
            <select
              value={etaForm.weather}
              onChange={setField('weather')}
              className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
            >
              <option value="clear">clear</option>
              <option value="rain">rain</option>
              <option value="storm">storm</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="text-slate-500">Dispatch time (ISO, optional)</span>
            <input
              value={etaForm.dispatch_time}
              onChange={setField('dispatch_time')}
              placeholder="defaults to now"
              className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
            />
          </label>
        </div>
        <button
          onClick={() => etaMutation.mutate()}
          disabled={etaMutation.isPending}
          className="mt-4 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {etaMutation.isPending ? 'Predicting…' : 'Predict ETA'}
        </button>
        {etaMutation.isError ? (
          <p className="mt-3 text-sm text-red-600">
            Prediction failed — is the backend and model available?
          </p>
        ) : null}
        {etaResult ? (
          <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm">
            <p className="text-2xl font-bold text-brand-700">
              {etaResult.predicted_eta_minutes} min
            </p>
            <p className="mt-1 text-slate-600">
              ≈ {etaResult.interval.lower_minutes}–{etaResult.interval.upper_minutes} min
              <span className="ml-2 text-xs text-slate-400">
                ({etaResult.interval.method} interval, approximate)
              </span>
            </p>
            <p className="mt-2 text-xs text-slate-500">
              Model version {etaResult.model_version ?? '—'} · run{' '}
              {etaResult.model_run_id ?? '—'} ·{' '}
              {new Date(etaResult.prediction_timestamp).toLocaleString()}
            </p>
            <details className="mt-2 text-xs text-slate-500">
              <summary>Feature vector used</summary>
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-white p-2">
                {JSON.stringify(etaResult.features_used, null, 2)}
              </pre>
            </details>
          </div>
        ) : null}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="font-semibold">Anomaly Scoring (Isolation Forest)</h2>
        <div className="mt-4 grid grid-cols-2 gap-3">
          {(Object.keys(DEFAULT_TELEMETRY) as (keyof typeof DEFAULT_TELEMETRY)[]).map(
            (key) => (
              <label key={key} className="text-sm">
                <span className="text-slate-500">{key}</span>
                <input
                  type="number"
                  value={telemetry[key]}
                  onChange={(e) =>
                    setTelemetry((t) => ({ ...t, [key]: Number(e.target.value) }))
                  }
                  className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5"
                />
              </label>
            ),
          )}
        </div>
        <button
          onClick={() => anomalyMutation.mutate()}
          disabled={anomalyMutation.isPending}
          className="mt-4 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {anomalyMutation.isPending ? 'Scoring…' : 'Score telemetry'}
        </button>
        {anomalyResult ? (
          <div className="mt-4 rounded-lg bg-slate-50 p-4 text-sm">
            {anomalyResult.map((r, i) => (
              <div key={i}>
                <p className="font-semibold">
                  Score {r.anomaly_score.toFixed(3)} —{' '}
                  <span className={r.anomaly_flag ? 'text-red-600' : 'text-emerald-600'}>
                    {r.anomaly_flag ? 'UNUSUAL PATTERN' : 'no unusual pattern'}
                  </span>
                </p>
                <p className="mt-1 text-xs text-slate-500">{r.description}</p>
              </div>
            ))}
          </div>
        ) : null}
        <p className="mt-4 text-xs text-slate-400">
          {modelInfo.data?.anomaly_model
            ? `Model: ${modelInfo.data.anomaly_model.method}, contamination=${modelInfo.data.anomaly_model.contamination}`
            : 'Anomaly model not loaded.'}
        </p>
      </section>
    </div>
  );
}

