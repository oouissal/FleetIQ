# Monitoring — Offline / Simulated

FleetIQ ships **offline monitoring reports**, clearly labelled as such.
There is no live production stream in this project, so nothing here is a
real production monitor.

## What is monitored

1. **Data quality** (`data_quality/`)
   * Pandera schema + range validation on batch data (telemetry, GPS,
     deliveries).
   * Reports: valid/invalid counts, failure summary, sample failures;
     invalid rows are exported to parquet (never silently dropped).
   * Run: `python -m data_quality.cli --input data/raw --all --output monitoring/reports`

2. **Data + feature drift** (`ml/drift.py`)
   * Evidently `DataDriftPreset` comparing a reference window vs a current
     window over the ETA features + target.
   * Writes `monitoring/reports/drift_report.html` and `drift_summary.json`.
   * Run: `python ml/drift.py --raw data/raw --out monitoring/reports`

3. **Data quality in the streaming path**
   * The Spark job routes invalid rows to `bronze/_invalid/<type>` with
     the failing rule names attached, and logs validation failures
     per micro-batch.

4. **Model + prediction metadata**
   * MLflow experiment `supply-chain-intelligence` records params,
     metrics, training duration, artifacts.
   * `/api/model/info` exposes the real measured metrics.

## Honest labelling

Every generated report includes the field
`"label": "Offline / Simulated Monitoring"`. The README, the drift module
docstring and this document repeat it: these are on-demand reports over
synthetic data, not a live monitor.

## Airflow

The batch DAG (`airflow/dags/daily_feature_pipeline.py`) schedules the
offline chain daily: validate → aggregates → features → evaluation →
monitoring report. Streaming vs batch is explained in the DAG docstring
and in the README.
