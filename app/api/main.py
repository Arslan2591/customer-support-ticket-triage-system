"""FastAPI surface for the triage system.

Endpoints
  GET  /health    liveness + dependency checks (model loaded, db reachable)
  POST /triage    classify + prioritize + route one ticket (explainable)
  POST /feedback  record a human correction (closes the learning loop)
  GET  /metrics   workflow metrics derived from the audit log
  GET  /queue     recent triaged tickets (powers the operator UI)

The core logic lives in app/services; this module only adapts it to HTTP.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.config import get_settings
from app.schemas import (
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    TriageRequest,
    TriageResponse,
)
from app.services.metrics import runtime_metrics
from app.services.model import TriageModel
from app.services.storage import Storage
from app.services.triage import TriageService

logger = logging.getLogger("triage.api")

# Process-wide singletons, populated on startup.
_state: dict[str, object] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    _state["storage"] = Storage(settings.db_path)

    if os.path.exists(settings.model_path):
        model = TriageModel.load(settings.model_path)
        _state["service"] = TriageService(model, settings.confidence_threshold)
        logger.info("Model loaded from %s", settings.model_path)
    else:
        _state["service"] = None
        logger.warning(
            "No model at %s — run `python -m scripts.train` first. "
            "/triage will return 503 until then.",
            settings.model_path,
        )
    yield
    _state.clear()


app = FastAPI(
    title="Customer Support Ticket Triage System",
    version=get_settings().version,
    description="Classifies, prioritizes, and routes support tickets with an "
                "explainable decision path and a human-in-the-loop override.",
    lifespan=lifespan,
)


# --- dependencies -----------------------------------------------------------
def get_storage() -> Storage:
    return _state["storage"]  # type: ignore[return-value]


def get_service() -> TriageService:
    svc = _state.get("service")
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model not loaded. Run `python -m scripts.train` and restart.",
        )
    return svc  # type: ignore[return-value]


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Shared-secret auth for write endpoints. No-op if TRIAGE_API_KEY unset."""
    settings = get_settings()
    if settings.api_key:
        if x_api_key != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid X-API-Key header.",
            )


# --- routes -----------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    settings = get_settings()
    storage: Storage = _state.get("storage")  # type: ignore[assignment]
    db_ok = storage.ping() if storage else False
    model_loaded = _state.get("service") is not None
    return HealthResponse(
        status="ok" if (db_ok and model_loaded) else "degraded",
        model_loaded=model_loaded,
        db_ok=db_ok,
        version=settings.version,
    )


@app.post("/triage", response_model=TriageResponse, tags=["triage"],
          dependencies=[Depends(require_api_key)])
def triage(
    req: TriageRequest,
    service: TriageService = Depends(get_service),
    storage: Storage = Depends(get_storage),
) -> TriageResponse:
    decision = service.triage(
        subject=req.subject,
        body=req.body,
        customer_tier=req.customer_tier,
        ticket_id=req.ticket_id,
    )
    # Persist the full decision + inputs as the audit trail.
    storage.record_triage({
        **decision.as_dict(),
        "subject": req.subject,
        "body": req.body,
        "customer_tier": req.customer_tier,
    })
    return TriageResponse(**decision.as_dict())


@app.post("/feedback", response_model=FeedbackResponse, tags=["triage"],
          dependencies=[Depends(require_api_key)])
def feedback(
    req: FeedbackRequest,
    storage: Storage = Depends(get_storage),
) -> FeedbackResponse:
    prior = storage.latest_event(req.ticket_id)
    if prior is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No triaged ticket with id '{req.ticket_id}'.",
        )

    # An override is any provided correction that differs from the system's call.
    was_override = any([
        req.correct_category and req.correct_category != prior["category"],
        req.correct_priority and req.correct_priority != prior["priority"],
        req.correct_team and req.correct_team != prior["assigned_team"],
    ])

    storage.record_feedback(
        ticket_id=req.ticket_id,
        correct_category=req.correct_category,
        correct_priority=req.correct_priority,
        correct_team=req.correct_team,
        reviewer=req.reviewer,
        note=req.note,
        was_override=was_override,
    )
    return FeedbackResponse(ticket_id=req.ticket_id, recorded=True,
                            was_override=was_override)


@app.get("/metrics", tags=["ops"])
def metrics(storage: Storage = Depends(get_storage)) -> dict:
    return runtime_metrics(storage.counts())


@app.get("/queue", tags=["triage"])
def queue(limit: int = 50, storage: Storage = Depends(get_storage)) -> list[dict]:
    return storage.recent_events(limit=limit)
