"""Pydantic request/response schemas for the API boundary.

Validation here gives the API useful, explicit error messages (Step 12) and
keeps the service layer free of HTTP concerns.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TriageRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500,
                         description="Ticket subject line.")
    body: str = Field(default="", max_length=10_000,
                      description="Ticket body / description.")
    customer_tier: str = Field(default="Free",
                               description="Free | Pro | Enterprise | VIP.")
    ticket_id: Optional[str] = Field(default=None,
                                     description="Optional caller-supplied id.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "ticket_id": "T-1001",
                "subject": "Production API is down",
                "body": "Our checkout has been returning 500s for 20 minutes.",
                "customer_tier": "Enterprise",
            }
        }
    }


class Reason(BaseModel):
    """One line of the explainable decision path."""
    layer: str = Field(description="Which layer fired: model | rule | routing | confidence.")
    detail: str


class TriageResponse(BaseModel):
    ticket_id: str
    category: str
    priority: str
    assigned_team: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool
    reasons: list[Reason]
    correlation_id: str


class FeedbackRequest(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    correct_category: Optional[str] = None
    correct_priority: Optional[str] = None
    correct_team: Optional[str] = None
    reviewer: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=2_000)


class FeedbackResponse(BaseModel):
    ticket_id: str
    recorded: bool
    was_override: bool


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    db_ok: bool
    version: str
