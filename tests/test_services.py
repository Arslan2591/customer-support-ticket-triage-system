"""Unit tests for the pure business logic (no HTTP, no DB)."""
from __future__ import annotations

from app.domain import max_priority, normalize_tier
from app.services.preprocessing import clean_text, combine
from app.services.routing import route
from app.services.rules import apply_rules


# --- preprocessing ----------------------------------------------------------
def test_combine_handles_missing_fields():
    assert combine(None, None) == ""
    assert combine("Hi", None).startswith("hi")


def test_clean_text_collapses_whitespace():
    assert clean_text("  Hello   World \n") == "hello world"


# --- domain helpers ---------------------------------------------------------
def test_normalize_tier_defaults_to_free():
    assert normalize_tier("bogus") == "Free"
    assert normalize_tier("vip") == "VIP"
    assert normalize_tier(None) == "Free"


def test_max_priority_orders_correctly():
    assert max_priority("Low", "Urgent") == "Urgent"
    assert max_priority("High", "Medium") == "High"


# --- rules (the guardrail layer) --------------------------------------------
def test_urgent_keyword_forces_urgent():
    out = apply_rules("our production system is down", "Free", "Low")
    assert out.priority == "Urgent"
    assert out.matched_keywords


def test_vip_tier_raises_priority_floor():
    out = apply_rules("just a question", "Enterprise", "Low")
    assert out.priority == "High"  # VIP_PRIORITY_FLOOR


def test_rules_never_lower_priority():
    # Model already said Urgent; a Free-tier no-keyword ticket stays Urgent.
    out = apply_rules("normal text", "Free", "Urgent")
    assert out.priority == "Urgent"


# --- routing + exception path -----------------------------------------------
def test_routing_maps_category_to_team():
    team, needs_review, _ = route("Billing", confidence=0.9, threshold=0.45)
    assert team == "Billing Team"
    assert needs_review is False


def test_low_confidence_goes_to_human_review():
    team, needs_review, reason = route("Billing", confidence=0.2, threshold=0.45)
    assert needs_review is True
    assert team == "Human Review Queue"
    assert "threshold" in reason


def test_confidence_exactly_at_threshold_is_auto_assigned():
    # Boundary: >= threshold is auto-assigned (not < threshold).
    team, needs_review, _ = route("Bug", confidence=0.45, threshold=0.45)
    assert needs_review is False
    assert team == "Engineering"


# --- triage service (model + rules + routing together) ----------------------
def test_triage_happy_path(service):
    d = service.triage(
        subject="I was charged twice", body="duplicate charge on my invoice",
        customer_tier="Pro",
    )
    assert d.category in {"Billing", "Account", "General", "Technical", "Bug", "Feature Request"}
    assert d.priority in {"Low", "Medium", "High", "Urgent"}
    assert d.assigned_team
    assert 0.0 <= d.confidence <= 1.0
    assert d.reasons  # explainable path is populated
    assert d.correlation_id


def test_triage_urgent_enterprise_is_escalated(service):
    d = service.triage(
        subject="Production outage", body="everything is down, this is urgent",
        customer_tier="Enterprise",
    )
    assert d.priority == "Urgent"
    assert any(r["layer"] == "rule" for r in d.reasons)


def test_triage_generates_ticket_id_when_missing(service):
    d = service.triage(subject="hello", body="hi")
    assert d.ticket_id.startswith("T-")
