"""FleetIQ daily batch pipeline (Airflow).

Batch-only orchestration. The real-time Kafka -> Spark pipeline is a
continuous streaming application and is NOT orchestrated by Airflow — it
runs as a long-lived docker service. This DAG runs the daily batch jobs
that complement the stream:

    validate data -> generate aggregates -> feature engineering
                   -> model evaluation -> offline monitoring report

Differences (documented in README):
    * Streaming: continuous, low-latency, event-time windows, runs 24/7.
    * Batch:     scheduled, high-throughput, full-dataset recomputation.

Requires the Airflow profile: `docker compose --profile airflow up airflow`
and the deps from requirements.txt inside the airflow image.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.operators.bash import BashOperator

from airflow import DAG

default_args = {
    "owner": "fleetiq",
    "depends_on_past": False,
    "start_date": datetime(2026, 10, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="daily_feature_pipeline",
    default_args=default_args,
    schedule_interval="0 3 * * *",  # daily 03:00 UTC
    catchup=False,
    max_active_runs=1,
    tags=["batch", "fleetiq"],
    description="Daily batch: validate -> aggregate -> features -> "
                "evaluate -> offline monitoring",
) as dag:
    validate = BashOperator(
        task_id="validate_data",
        bash_command=(
            "cd /opt/airflow && python -m data_quality.cli --input data/raw "
            "--all --output monitoring/reports"
        ),
    )

    aggregates = BashOperator(
        task_id="generate_aggregates",
        bash_command=(
            "cd /opt/airflow && python -c \"from pathlib import Path; "
            "from ml.gold import build_all; "
            "build_all(Path('data/raw'), Path('data_lake/gold'))\""
        ),
    )

    features = BashOperator(
        task_id="feature_engineering",
        bash_command=(
            "cd /opt/airflow && python -c \"from pathlib import Path; "
            "from ml.features import build_eta_dataset; import pandas as pd; "
            "df = build_eta_dataset(Path('data/raw')); "
            "Path('data/features').mkdir(parents=True, exist_ok=True); "
            "df.to_parquet('data/features/eta_features.parquet')\""
        ),
    )

    evaluate = BashOperator(
        task_id="model_evaluation",
        bash_command=(
            "cd /opt/airflow && python -m ml.train_eta --raw data/raw "
            "--results ml/mlruns_meta/eta_results.json"
        ),
    )

    monitoring = BashOperator(
        task_id="offline_monitoring_report",
        bash_command=(
            "cd /opt/airflow && python ml/drift.py --raw data/raw "
            "--out monitoring/reports"
        ),
    )

    validate >> aggregates >> features >> evaluate >> monitoring
