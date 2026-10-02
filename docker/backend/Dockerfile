# FleetIQ FastAPI backend image
FROM python:3.12-slim

WORKDIR /app

# API + ML serving dependencies (subset of requirements.txt)
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    "pydantic>=2" \
    pydantic-settings \
    pandas \
    pyarrow \
    s3fs \
    joblib \
    scikit-learn \
    xgboost \
    mlflow \
    python-multipart \
    httpx

COPY api /app/api
COPY ml /app/ml
COPY streaming /app/streaming

ENV FLEETIQ_API_HOST=0.0.0.0
ENV FLEETIQ_API_PORT=8000

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
