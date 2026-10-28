"""Routing service: map a predicted category to the team that owns it.

Low-confidence tickets are diverted to the human-review queue instead of
being auto-assigned — this is the system's primary exception path.
"""
from __future__ import annotations

from app.domain import CATEGORY_TO_TEAM, HUMAN_REVIEW_TEAM


def route(category: str, confidence: float, threshold: float) -> tuple[str, bool, str]:
    """Return (assigned_team, needs_review, reason).

    If confidence is below the threshold we withhold auto-assignment and send
    the ticket to a human, because a wrong auto-route is more expensive than a
    short human glance.
    """
    if confidence < threshold:
        return (
            HUMAN_REVIEW_TEAM,
            True,
            f"Confidence {confidence:.0%} is below the {threshold:.0%} "
            f"threshold — routed to a human instead of auto-assigning.",
        )

    team = CATEGORY_TO_TEAM.get(category, HUMAN_REVIEW_TEAM)
    if team == HUMAN_REVIEW_TEAM:
        return team, True, f"No team mapping for category '{category}'."

    return team, False, f"Category '{category}' maps to {team}."
