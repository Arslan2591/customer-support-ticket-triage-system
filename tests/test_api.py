"""Integration tests for the FastAPI surface and the feedback loop."""
from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


# --- happy path -------------------------------------------------------------
def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["model_loaded"] is True
    assert body["db_ok"] is True


def test_triage_endpoint_returns_decision(client):
    r = client.post("/triage", json={
        "subject": "Cannot access my account",
        "body": "password reset email never arrives",
        "customer_tier": "Pro",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["assigned_team"]
    assert d["reasons"]
    assert "correlation_id" in d


# --- invalid / missing input ------------------------------------------------
def test_triage_rejects_missing_subject(client):
    r = client.post("/triage", json={"body": "no subject here"})
    assert r.status_code == 422  # pydantic validation error


def test_triage_rejects_empty_subject(client):
    r = client.post("/triage", json={"subject": "", "body": "x"})
    assert r.status_code == 422


# --- feedback loop (override captured) --------------------------------------
def test_feedback_override_is_flagged(client):
    t = client.post("/triage", json={
        "subject": "General question about pricing", "body": "how much is pro?",
        "customer_tier": "Free",
    }).json()

    # Force a correction that differs from the system's category.
    different = "Billing" if t["category"] != "Billing" else "Technical"
    r = client.post("/feedback", json={
        "ticket_id": t["ticket_id"],
        "correct_category": different,
        "reviewer": "tester",
    })
    assert r.status_code == 200
    assert r.json()["was_override"] is True


def test_feedback_confirmation_is_not_override(client):
    t = client.post("/triage", json={
        "subject": "Add a teammate", "body": "please add a user",
        "customer_tier": "Free",
    }).json()
    r = client.post("/feedback", json={
        "ticket_id": t["ticket_id"],
        "correct_category": t["category"],
        "correct_priority": t["priority"],
        "correct_team": t["assigned_team"],
    })
    assert r.json()["was_override"] is False


# --- dependency / not-found failure -----------------------------------------
def test_feedback_unknown_ticket_returns_404(client):
    r = client.post("/feedback", json={"ticket_id": "T-does-not-exist"})
    assert r.status_code == 404


def test_triage_503_when_model_missing(env):
    """Dependency failure: no model artifact -> /triage is unavailable, but
    /health still responds (degraded)."""
    import os
    os.remove(env.model_path) if os.path.exists(env.model_path) else None
    import app.api.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        assert c.get("/health").json()["model_loaded"] is False
        r = c.post("/triage", json={"subject": "hi", "body": "x"})
        assert r.status_code == 503


# --- authorization failure --------------------------------------------------
def test_api_key_enforced_when_configured(env, trained_model, monkeypatch):
    monkeypatch.setenv("TRIAGE_API_KEY", "secret123")
    import app.config as config
    config.get_settings.cache_clear()
    import app.api.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        # Missing key -> 401
        assert c.post("/triage", json={"subject": "hi", "body": "x"}).status_code == 401
        # Correct key -> 200
        ok = c.post("/triage", json={"subject": "hi", "body": "x"},
                    headers={"X-API-Key": "secret123"})
        assert ok.status_code == 200


# --- duplicate / retry behavior ---------------------------------------------
def test_duplicate_triage_same_ticket_id_keeps_latest(client):
    """Retrying triage for the same ticket_id appends a new audit event and
    /feedback resolves against the most recent one."""
    client.post("/triage", json={
        "ticket_id": "T-DUP", "subject": "first", "body": "x", "customer_tier": "Free",
    })
    second = client.post("/triage", json={
        "ticket_id": "T-DUP", "subject": "second production outage urgent",
        "body": "down", "customer_tier": "Free",
    }).json()
    # Feedback should resolve against the latest (second) event without error.
    r = client.post("/feedback", json={
        "ticket_id": "T-DUP", "correct_priority": second["priority"],
    })
    assert r.status_code == 200


# --- regression -------------------------------------------------------------
def test_regression_vip_low_confidence_still_escalates(client):
    """Regression guard: a VIP ticket whose category is uncertain must still be
    escalated to >= High by the rule layer even while routed to human review.
    (Early build applied the VIP floor only on the auto-assign path.)"""
    d = client.post("/triage", json={
        "subject": "???", "body": "unclear text zzz", "customer_tier": "VIP",
    }).json()
    from app.domain import PRIORITY_ORDER
    assert PRIORITY_ORDER[d["priority"]] >= PRIORITY_ORDER["High"]
