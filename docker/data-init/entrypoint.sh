#!/bin/sh
# FleetIQ data-init: generate, train, upload. Exits non-zero on failure so
# compose can report it via depends_on conditions.
set -e

echo "==> [1/5] Generating synthetic historical dataset"
python -m data_generator \
  --vehicles "${GENERATOR_VEHICLES:-150}" \
  --events "${GENERATOR_EVENTS:-150000}" \
  --days 3 \
  --output-dir /data/raw \
  --seed "${GENERATOR_SEED:-42}"

echo "==> [2/5] Training ETA models (MLflow: ${MLFLOW_TRACKING_URI})"
python -m ml.train_eta --raw /data/raw \
  --tracking-uri "${MLFLOW_TRACKING_URI}" \
  --results /data/ml_meta/eta_results.json

echo "==> [3/5] Training anomaly detection model"
python -m ml.train_anomaly --raw /data/raw \
  --out /data/gold/anomalies \
  --tracking-uri "${MLFLOW_TRACKING_URI}"

echo "==> [4/5] Building batch gold tables"
python -c "from pathlib import Path; from ml.gold import build_all; build_all(Path('/data/raw'), Path('/data/gold'))"

echo "==> [5/5] Publishing gold tables + metadata"

if [ -n "${S3_ENDPOINT}" ]; then
  python - <<'PY'
import os
import boto3
from botocore.client import Config

s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=os.environ["S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    config=Config(signature_version="s3v4"),
)
for path in os.listdir("/data/gold"):
    src = f"/data/gold/{path}"
    if os.path.isfile(src):
        s3.upload_file(src, "gold", path)
        print(f"  uploaded gold/{path}")
for f in ("telemetry.parquet", "gps.parquet", "deliveries.parquet",
          "routes.parquet", "vehicles.parquet"):
    src = f"/data/raw/{f}"
    if os.path.isfile(src):
        s3.upload_file(src, "raw", f)
        print(f"  uploaded raw/{f}")
print("  upload complete")
PY
else
  # filesystem-storage mode (docker-compose.fs.yml): stage into the shared
  # volume layout the backend and API read from.
  mkdir -p /data/lake/gold /data/lake/raw
  cp /data/gold/* /data/lake/gold/ 2>/dev/null || true
  cp -r /data/gold/anomalies /data/lake/gold/ 2>/dev/null || true
  cp /data/raw/*.parquet /data/lake/raw/ 2>/dev/null || true
  echo "  staged to /data/lake (filesystem storage mode)"
fi

echo "==> data-init finished"
