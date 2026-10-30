"""Streamlit operator console for the triage system.

Demonstrates the real workflow end to end:
  submit a ticket -> see the explainable decision -> work the queue ->
  override a wrong call (which is captured as feedback) -> watch the metrics.

The UI talks to the FastAPI service over HTTP (client -> API -> storage),
matching the deployed architecture rather than calling internals directly.

Run:  streamlit run app/ui/streamlit_app.py
"""
from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

DEFAULT_API = os.environ.get("TRIAGE_API_URL", "http://localhost:8000")

PRIORITY_COLORS = {
    "Urgent": "#d7263d",
    "High": "#f46036",
    "Medium": "#2e86ab",
    "Low": "#5b8c5a",
}

TIERS = ["Free", "Pro", "Enterprise", "VIP"]

st.set_page_config(page_title="Ticket Triage Console", page_icon="🎫", layout="wide")


# --- helpers ----------------------------------------------------------------
def api_headers() -> dict:
    key = st.session_state.get("api_key", "")
    return {"X-API-Key": key} if key else {}


def get_json(path: str, **params):
    base = st.session_state["api_url"]
    r = httpx.get(f"{base}{path}", params=params, headers=api_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def post_json(path: str, payload: dict):
    base = st.session_state["api_url"]
    r = httpx.post(f"{base}{path}", json=payload, headers=api_headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def priority_badge(priority: str) -> str:
    color = PRIORITY_COLORS.get(priority, "#888")
    return (f"<span style='background:{color};color:white;padding:3px 10px;"
            f"border-radius:12px;font-weight:600;font-size:0.85em'>{priority}</span>")


# --- sidebar ----------------------------------------------------------------
st.session_state.setdefault("api_url", DEFAULT_API)
st.session_state.setdefault("api_key", "")

with st.sidebar:
    st.header("Connection")
    st.session_state["api_url"] = st.text_input("API URL", st.session_state["api_url"])
    st.session_state["api_key"] = st.text_input(
        "API key (if enabled)", st.session_state["api_key"], type="password"
    )
    try:
        h = get_json("/health")
        if h["status"] == "ok":
            st.success("API healthy")
        else:
            st.warning(f"API: {h['status']}")
        st.caption(f"model_loaded={h['model_loaded']} · db_ok={h['db_ok']} "
                   f"· v{h['version']}")
    except Exception as e:  # noqa: BLE001
        st.error("Cannot reach API")
        st.caption(str(e))
        st.caption("Start it with:  uvicorn app.api.main:app --reload")

st.title("🎫 Customer Support Ticket Triage")

tab_triage, tab_queue, tab_metrics = st.tabs(
    ["Triage a ticket", "Operator queue", "Metrics"]
)

# --- tab 1: triage ----------------------------------------------------------
with tab_triage:
    st.subheader("Submit a ticket")
    with st.form("triage_form"):
        c1, c2 = st.columns([3, 1])
        subject = c1.text_input("Subject", "Production API is down")
        tier = c2.selectbox("Customer tier", TIERS, index=2)
        body = st.text_area(
            "Body",
            "Our checkout has been returning 500 errors for the last 20 minutes.",
            height=120,
        )
        submitted = st.form_submit_button("Triage ticket", type="primary")

    if submitted:
        try:
            result = post_json("/triage", {
                "subject": subject, "body": body, "customer_tier": tier,
            })
            st.session_state["last_result"] = result
        except Exception as e:  # noqa: BLE001
            st.error(f"Triage failed: {e}")

    result = st.session_state.get("last_result")
    if result:
        st.markdown("### Decision")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Category", result["category"])
        m2.markdown("**Priority**<br>" + priority_badge(result["priority"]),
                    unsafe_allow_html=True)
        m3.metric("Assigned team", result["assigned_team"])
        m4.metric("Confidence", f"{result['confidence']:.0%}")

        if result["needs_review"]:
            st.warning("⚠️ Low confidence — routed to the Human Review Queue "
                       "instead of auto-assigning.")
        else:
            st.success("Auto-assigned with confidence above threshold.")

        st.markdown("#### Why (explainable decision path)")
        for r in result["reasons"]:
            st.markdown(f"- **{r['layer']}** — {r['detail']}")
        st.caption(f"ticket_id={result['ticket_id']} · "
                   f"correlation_id={result['correlation_id']}")

# --- tab 2: operator queue --------------------------------------------------
with tab_queue:
    st.subheader("Recent tickets")
    try:
        rows = get_json("/queue", limit=50)
    except Exception as e:  # noqa: BLE001
        rows = []
        st.error(f"Cannot load queue: {e}")

    if rows:
        df = pd.DataFrame(rows)[
            ["ticket_id", "customer_tier", "category", "priority",
             "assigned_team", "confidence", "needs_review"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("#### Override a decision (captured as feedback)")
        ids = [r["ticket_id"] for r in rows]
        with st.form("override_form"):
            sel = st.selectbox("Ticket", ids)
            cur = next(r for r in rows if r["ticket_id"] == sel)
            c1, c2, c3 = st.columns(3)
            new_cat = c1.text_input("Correct category", cur["category"])
            new_pri = c2.text_input("Correct priority", cur["priority"])
            new_team = c3.text_input("Correct team", cur["assigned_team"])
            reviewer = st.text_input("Reviewer", "operator@demo")
            note = st.text_input("Note", "")
            ov = st.form_submit_button("Submit feedback", type="primary")
        if ov:
            try:
                resp = post_json("/feedback", {
                    "ticket_id": sel,
                    "correct_category": new_cat,
                    "correct_priority": new_pri,
                    "correct_team": new_team,
                    "reviewer": reviewer,
                    "note": note,
                })
                if resp["was_override"]:
                    st.success("Override recorded — the system's call was corrected.")
                else:
                    st.info("Feedback recorded — confirmed the system was correct.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Feedback failed: {e}")
    else:
        st.info("No tickets yet. Triage one in the first tab.")

# --- tab 3: metrics ---------------------------------------------------------
with tab_metrics:
    st.subheader("Workflow metrics (from the live audit log)")
    try:
        m = get_json("/metrics")
        c1, c2, c3 = st.columns(3)
        c1.metric("Tickets triaged", m["tickets_triaged"])
        c2.metric("Auto-containment", f"{m['auto_containment_rate']:.0%}")
        c3.metric("Review rate", f"{m['review_rate']:.0%}")
        c4, c5 = st.columns(2)
        c4.metric("Feedback captured", m["feedback_captured"])
        c5.metric("Override rate", f"{m['override_rate']:.0%}")
        st.caption("Quality metrics (macro F1, high-priority recall) are printed "
                   "by `python -m scripts.train` on a held-out split.")
    except Exception as e:  # noqa: BLE001
        st.error(f"Cannot load metrics: {e}")
