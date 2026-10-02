"""FleetIQ API — FastAPI application entry point.

Run locally:
    uvicorn api.main:app --host 0.0.0.0 --port 8000

OpenAPI docs are served at /docs (Swagger UI) and /redoc.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import get_config
from api.routers import analytics, anomalies, fleet, models
from api.schemas import HealthResponse
from api.services.models import anomaly_model_info, eta_model_info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    log.info("FleetIQ API starting (gold_root=%s, mlflow=%s)",
             cfg.gold_root, cfg.mlflow_tracking_uri or "local")
    yield
    log.info("FleetIQ API shutting down")


app = FastAPI(
    title="FleetIQ — Real-Time Supply Chain Intelligence API",
    description=(
        "API for the FleetIQ platform: fleet state, routes, deliveries, "
        "anomalies, KPIs and ML predictions. All data is SYNTHETIC.\n\n"
        "Limitations: synthetic data; simulated local streaming; "
        "unsupervised anomaly detection; experimental ETA predictions."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

cfg = get_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Structured request logging (observability)."""
    t0 = time.time()
    response = await call_next(request)
    log.info("%s %s -> %s (%.0fms)",
             request.method, request.url.path, response.status_code,
             1000 * (time.time() - t0))
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal error"})


@app.get("/health", response_model=HealthResponse,
         summary="Service + data availability health check")
def health() -> HealthResponse:
    cfg = get_config()
    from api.services.store import GoldStore

    store = GoldStore(cfg)
    data_ok = store.exists("vehicle_snapshot")
    models_ok = bool(eta_model_info(cfg) and anomaly_model_info(cfg))
    return HealthResponse(status="ok" if data_ok else "degraded",
                          data_available=data_ok,
                          models_available=models_ok)


app.include_router(fleet.router)
app.include_router(analytics.router)
app.include_router(anomalies.router)
app.include_router(models.router)
