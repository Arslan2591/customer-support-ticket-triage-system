"""Domain taxonomy and business constants.

Single source of truth for categories, priorities, tiers, teams, and the
rule-layer inputs (VIP tiers + urgent keywords). Imported by the data
generator, the rule engine, the router, and the model so they can never
drift apart.
"""
from __future__ import annotations

# --- Classification targets -------------------------------------------------
CATEGORIES: list[str] = [
    "Billing",
    "Technical",
    "Account",
    "Feature Request",
    "Bug",
    "General",
]

PRIORITIES: list[str] = ["Low", "Medium", "High", "Urgent"]

# Ordered so we can take the *maximum* of a model prediction and a rule floor.
PRIORITY_ORDER: dict[str, int] = {p: i for i, p in enumerate(PRIORITIES)}

# --- Customer tiers ---------------------------------------------------------
TIERS: list[str] = ["Free", "Pro", "Enterprise", "VIP"]

# Tiers that get a guaranteed minimum priority (business guardrail).
VIP_TIERS: set[str] = {"Enterprise", "VIP"}

# Priority floor applied when a VIP/Enterprise customer files a ticket.
VIP_PRIORITY_FLOOR: str = "High"

# --- Routing ----------------------------------------------------------------
CATEGORY_TO_TEAM: dict[str, str] = {
    "Billing": "Billing Team",
    "Technical": "Technical Support",
    "Account": "Account Management",
    "Feature Request": "Product Team",
    "Bug": "Engineering",
    "General": "Tier-1 Support",
}

HUMAN_REVIEW_TEAM: str = "Human Review Queue"

# --- Rule layer -------------------------------------------------------------
# Presence of any of these (word-boundary match) forces priority to Urgent.
# Kept deliberately small and auditable — this is a safety guardrail, not ML.
URGENT_KEYWORDS: list[str] = [
    "outage",
    "down",
    "cannot access",
    "can't access",
    "not working",
    "production",
    "data loss",
    "breach",
    "security",
    "hacked",
    "urgent",
    "asap",
    "emergency",
    "critical",
    "payment failed",
    "charged twice",
]


def normalize_tier(tier: str | None) -> str:
    """Map arbitrary input to a known tier, defaulting to Free.

    Case-insensitive on purpose: a caller sending "vip" or "enterprise" must
    still get the VIP/Enterprise escalation guarantee. (str.title() would turn
    "vip" into "Vip" and silently drop it to Free — a bug caught in testing.)
    """
    if not tier:
        return "Free"
    t = tier.strip().casefold()
    for known in TIERS:
        if t == known.casefold():
            return known
    return "Free"


def max_priority(a: str, b: str) -> str:
    """Return the higher-severity of two priority labels."""
    return a if PRIORITY_ORDER.get(a, 0) >= PRIORITY_ORDER.get(b, 0) else b
