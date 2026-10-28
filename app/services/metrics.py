"""Metrics — quality (offline eval) and workflow/business (runtime).

Quality metrics are computed on a held-out, stratified test split so the
numbers are honest rather than training-set optimism. Because the data is
synthetic, the README labels all of this as *simulated portfolio metrics*.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.metrics import f1_score, recall_score
from sklearn.model_selection import train_test_split

from app.domain import CATEGORY_TO_TEAM
from app.services.model import TriageModel
from app.services.preprocessing import combine
from app.services.rules import apply_rules
from app.services.routing import route

HIGH_PRIORITY = {"High", "Urgent"}

# Assumptions behind the business metric — stated, not hidden.
SECONDS_MANUAL_TRIAGE = 90      # avg. time for a human to read + route one ticket
SECONDS_HUMAN_REVIEW = 25       # time to confirm/correct a system suggestion


@dataclass
class QualityMetrics:
    n_test: int
    category_macro_f1: float
    priority_macro_f1: float
    routing_accuracy: float
    high_priority_recall: float
    auto_containment_rate: float   # fraction auto-assigned (not sent to review)


def evaluate(csv_path: str, confidence_threshold: float, test_size: float = 0.25,
             seed: int = 42) -> QualityMetrics:
    """Train on a split, evaluate the FULL pipeline (model + rules + routing)."""
    df = pd.read_csv(csv_path).fillna("")
    texts = [combine(s, b) for s, b in zip(df["subject"], df["body"])]

    idx = list(range(len(df)))
    train_idx, test_idx = train_test_split(
        idx, test_size=test_size, random_state=seed, stratify=df["category"]
    )

    model = TriageModel.train(
        [texts[i] for i in train_idx],
        [df["category"].iloc[i] for i in train_idx],
        [df["priority"].iloc[i] for i in train_idx],
    )

    svc_threshold = confidence_threshold
    true_cat, pred_cat = [], []
    true_pri, pred_pri = [], []
    true_team, pred_team = [], []
    auto_assigned = 0

    for i in test_idx:
        subject, body, tier = df["subject"].iloc[i], df["body"].iloc[i], df["customer_tier"].iloc[i]
        p = model.predict(subject, body)
        final_priority = apply_rules(combine(subject, body), tier, p.priority).priority
        team, needs_review, _ = route(p.category, p.category_confidence, svc_threshold)

        true_cat.append(df["category"].iloc[i])
        pred_cat.append(p.category)
        true_pri.append(df["priority"].iloc[i])
        pred_pri.append(final_priority)
        true_team.append(CATEGORY_TO_TEAM.get(df["category"].iloc[i], "Human Review Queue"))
        pred_team.append(team)
        if not needs_review:
            auto_assigned += 1

    n = len(test_idx)
    true_high = [1 if p in HIGH_PRIORITY else 0 for p in true_pri]
    pred_high = [1 if p in HIGH_PRIORITY else 0 for p in pred_pri]

    return QualityMetrics(
        n_test=n,
        category_macro_f1=round(f1_score(true_cat, pred_cat, average="macro"), 3),
        priority_macro_f1=round(f1_score(true_pri, pred_pri, average="macro"), 3),
        # Routing accuracy only counts auto-assigned tickets against truth.
        routing_accuracy=round(
            sum(1 for t, p in zip(true_team, pred_team) if t == p) / n, 3
        ),
        high_priority_recall=round(
            recall_score(true_high, pred_high, zero_division=0), 3
        ),
        auto_containment_rate=round(auto_assigned / n, 3),
    )


def estimated_hours_saved(n_tickets: int, auto_containment_rate: float) -> float:
    """Simulated business metric. Manual baseline vs. system-assisted time."""
    baseline = n_tickets * SECONDS_MANUAL_TRIAGE
    assisted = (
        n_tickets * auto_containment_rate * 0  # auto-assigned ~ no human time
        + n_tickets * (1 - auto_containment_rate) * SECONDS_HUMAN_REVIEW
    )
    return round((baseline - assisted) / 3600, 1)


def runtime_metrics(counts: dict[str, int]) -> dict[str, float]:
    """Workflow metrics derived from the live audit log."""
    events = counts.get("events", 0) or 0
    feedback = counts.get("feedback", 0) or 0
    overrides = counts.get("overrides", 0) or 0
    reviews = counts.get("needs_review", 0) or 0
    return {
        "tickets_triaged": events,
        "review_rate": round(reviews / events, 3) if events else 0.0,
        "auto_containment_rate": round((events - reviews) / events, 3) if events else 0.0,
        "override_rate": round(overrides / feedback, 3) if feedback else 0.0,
        "feedback_captured": feedback,
    }
