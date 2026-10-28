"""Deterministic rule layer — the auditable guardrail that overrides ML.

Real triage systems never let a probabilistic model have the last word on
safety-critical routing. Two rules run here:

  1. Urgent keyword match  -> force priority to "Urgent".
  2. VIP / Enterprise tier -> raise priority to at least VIP_PRIORITY_FLOOR.

Each rule that fires returns a human-readable reason so the decision path is
fully explainable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain import (
    URGENT_KEYWORDS,
    VIP_PRIORITY_FLOOR,
    VIP_TIERS,
    max_priority,
    normalize_tier,
)

# Pre-compile one word-boundary regex per keyword for clean matching.
_KEYWORD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (kw, re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)", re.IGNORECASE))
    for kw in URGENT_KEYWORDS
]


@dataclass
class RuleOutcome:
    priority: str
    reasons: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)


def apply_rules(text: str, customer_tier: str, model_priority: str) -> RuleOutcome:
    """Combine the model's predicted priority with deterministic overrides.

    Returns the final priority (never lower than the model's) plus the reasons
    for any override that fired.
    """
    tier = normalize_tier(customer_tier)
    priority = model_priority
    reasons: list[str] = []

    # Rule 1: urgent keywords
    hits = [kw for kw, pat in _KEYWORD_PATTERNS if pat.search(text or "")]
    if hits:
        priority = max_priority(priority, "Urgent")
        reasons.append(
            "Urgent keyword(s) detected: " + ", ".join(f"'{h}'" for h in hits)
        )

    # Rule 2: VIP / Enterprise floor
    if tier in VIP_TIERS:
        bumped = max_priority(priority, VIP_PRIORITY_FLOOR)
        if bumped != priority:
            reasons.append(
                f"{tier} customer: priority raised to at least "
                f"'{VIP_PRIORITY_FLOOR}'."
            )
        priority = bumped

    return RuleOutcome(priority=priority, reasons=reasons, matched_keywords=hits)
