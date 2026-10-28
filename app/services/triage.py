"""The triage orchestrator — the heart of the system.

Pipeline: model prediction -> rule overrides -> routing -> explainable result.
This is a pure function of its inputs (plus the loaded model); persistence and
HTTP live elsewhere, so this is trivially unit-testable.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from app.domain import normalize_tier
from app.services.model import TriageModel
from app.services.preprocessing import combine
from app.services.rules import apply_rules
from app.services.routing import route


@dataclass
class Decision:
    ticket_id: str
    category: str
    priority: str
    assigned_team: str
    confidence: float
    needs_review: bool
    reasons: list[dict]          # [{"layer":..., "detail":...}, ...]
    correlation_id: str

    def as_dict(self) -> dict:
        return asdict(self)


class TriageService:
    def __init__(self, model: TriageModel, confidence_threshold: float):
        self.model = model
        self.confidence_threshold = confidence_threshold

    def triage(
        self,
        subject: str,
        body: str = "",
        customer_tier: str = "Free",
        ticket_id: str | None = None,
    ) -> Decision:
        ticket_id = ticket_id or f"T-{uuid.uuid4().hex[:8]}"
        correlation_id = uuid.uuid4().hex
        tier = normalize_tier(customer_tier)
        text = combine(subject, body)

        reasons: list[dict] = []

        # 1. Model prediction
        pred = self.model.predict(subject, body)
        if pred.top_tokens:
            reasons.append({
                "layer": "model",
                "detail": (
                    f"Classified as '{pred.category}' "
                    f"({pred.category_confidence:.0%} confidence). "
                    f"Top signals: " + ", ".join(pred.top_tokens) + "."
                ),
            })
        else:
            reasons.append({
                "layer": "model",
                "detail": (
                    f"Classified as '{pred.category}' "
                    f"({pred.category_confidence:.0%} confidence)."
                ),
            })
        reasons.append({
            "layer": "model",
            "detail": (
                f"Predicted priority '{pred.priority}' "
                f"({pred.priority_confidence:.0%} confidence)."
            ),
        })

        # 2. Rule overrides (may raise priority; never lowers it)
        rule_outcome = apply_rules(text, tier, pred.priority)
        final_priority = rule_outcome.priority
        for r in rule_outcome.reasons:
            reasons.append({"layer": "rule", "detail": r})

        # 3. Routing + low-confidence exception path
        team, needs_review, route_reason = route(
            pred.category, pred.category_confidence, self.confidence_threshold
        )
        reasons.append({"layer": "routing", "detail": route_reason})

        return Decision(
            ticket_id=ticket_id,
            category=pred.category,
            priority=final_priority,
            assigned_team=team,
            confidence=round(pred.category_confidence, 4),
            needs_review=needs_review,
            reasons=reasons,
            correlation_id=correlation_id,
        )
