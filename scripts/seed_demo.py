"""Seed the audit log with a handful of representative tickets so the demo
queue and metrics page are populated out of the box.

Writes through the real service + storage layers (not raw SQL), so the seeded
rows are identical to what the API would produce.

Run:  python -m scripts.seed_demo
"""
from __future__ import annotations

from app.config import get_settings
from app.services.model import TriageModel
from app.services.storage import Storage
from app.services.triage import TriageService

SAMPLE_TICKETS = [
    # (subject, body, tier) — a mix that exercises every path.
    ("Production API is down", "Checkout returns 500s for all users.", "Enterprise"),
    ("I was charged twice this month", "Two identical charges on my card.", "Pro"),
    ("Please add dark mode", "Would love a dark theme for night shifts.", "Free"),
    ("Reset my password", "The reset email never arrives.", "Free"),
    ("Numbers on the report are wrong", "Totals don't match the raw data.", "Pro"),
    ("Need help", "Something is wrong and I'm not sure why.", "VIP"),
    ("Security breach suspected", "We think our account was accessed.", "Enterprise"),
    ("Question about pricing", "Do you offer a nonprofit discount?", "Free"),
    ("SSO login not working", "Intermittent 401 errors on login.", "Enterprise"),
    ("This isn't working", "Please advise.", "Pro"),
]


def main() -> None:
    settings = get_settings()
    model = TriageModel.load(settings.model_path)
    service = TriageService(model, settings.confidence_threshold)
    storage = Storage(settings.db_path)

    for subject, body, tier in SAMPLE_TICKETS:
        d = service.triage(subject=subject, body=body, customer_tier=tier)
        storage.record_triage({
            **d.as_dict(), "subject": subject, "body": body, "customer_tier": tier,
        })
        flag = " [REVIEW]" if d.needs_review else ""
        print(f"{d.ticket_id}  {d.category:<16} {d.priority:<7} -> "
              f"{d.assigned_team}{flag}")

    print(f"\nSeeded {len(SAMPLE_TICKETS)} tickets into {settings.db_path}")


if __name__ == "__main__":
    main()
