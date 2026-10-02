# FleetIQ one-shot data initialization:
#  1. generate a synthetic historical dataset
#  2. train + register ETA and anomaly models in the MLflow server
#  3. build batch gold tables and upload them to the MinIO gold bucket
# The container exits when done; backend waits for it via depends_on.
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pandas pyarrow numpy scipy \
    scikit-learn xgboost mlflow joblib \
    kafka-python \
    "pydantic>=2" pydantic-settings \
    pandera \
    boto3

COPY data_generator /app/data_generator
COPY ml /app/ml
COPY streaming /app/streaming
COPY scripts /app/scripts
COPY docker/data-init/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
