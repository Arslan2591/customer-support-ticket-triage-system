"""Generate a realistic *synthetic* support-ticket dataset.

No real customer data — anyone can run the whole project from this.
Labels follow the same policy the rule engine enforces (urgent keywords ->
Urgent; VIP/Enterprise -> at least High), so the dataset, the model, and the
rules stay coherent.

Run:  python -m data.generate_data            (writes data/tickets.csv)
      python -m data.generate_data --rows 800 --out data/tickets.csv
"""
from __future__ import annotations

import argparse
import csv
import random

from app.config import get_settings
from app.domain import (
    CATEGORY_TO_TEAM,
    URGENT_KEYWORDS,
    VIP_PRIORITY_FLOOR,
    VIP_TIERS,
    max_priority,
)

TIER_WEIGHTS = {"Free": 0.45, "Pro": 0.35, "Enterprise": 0.15, "VIP": 0.05}

# Per-category content. {subjects}/{bodies} are sampled and lightly combined.
TEMPLATES: dict[str, dict] = {
    "Billing": {
        "subjects": [
            "Question about my invoice",
            "I was charged twice this month",
            "Refund request for duplicate charge",
            "Update payment method",
            "Why did my subscription price change?",
            "Invoice does not match my plan",
        ],
        "bodies": [
            "I see two charges on my statement for the same billing period.",
            "Can you explain the line items on invoice {num}?",
            "I'd like to switch from monthly to annual billing.",
            "My card was declined but I was still charged.",
            "Please update my billing address and resend the receipt.",
        ],
        "base_priorities": ["Low", "Medium", "Medium", "High"],
    },
    "Technical": {
        "subjects": [
            "Unable to connect to the API",
            "Dashboard loads very slowly",
            "SSO login not working",
            "Webhook events are delayed",
            "Export to CSV fails",
            "Getting timeout errors",
        ],
        "bodies": [
            "The dashboard takes over 30 seconds to load since yesterday.",
            "Our integration receives 401 errors intermittently.",
            "Webhooks are arriving several minutes late.",
            "The CSV export button spins forever and never downloads.",
            "We see timeouts when calling the reports endpoint.",
        ],
        "base_priorities": ["Low", "Medium", "Medium", "High"],
    },
    "Account": {
        "subjects": [
            "Add a new team member",
            "Reset my password",
            "Change account owner",
            "Remove a user from the workspace",
            "Update company name on account",
            "Enable two-factor authentication",
        ],
        "bodies": [
            "Please add jane@example.com as an admin.",
            "I can't log in and the reset email never arrives.",
            "We need to transfer ownership to a new manager.",
            "Deactivate the seat for a teammate who left.",
            "How do I turn on 2FA for everyone on the plan?",
        ],
        "base_priorities": ["Low", "Low", "Medium", "Medium"],
    },
    "Feature Request": {
        "subjects": [
            "Please add dark mode",
            "Feature request: bulk export",
            "Can we get Slack notifications?",
            "Request for a mobile app",
            "Add support for custom fields",
            "Would love an audit log",
        ],
        "bodies": [
            "It would help a lot if we could export all records at once.",
            "Our team lives in Slack and wants alerts there.",
            "A dark theme would reduce eye strain for night shifts.",
            "We need custom fields to match our internal process.",
            "An audit log would help us with compliance reviews.",
        ],
        "base_priorities": ["Low", "Low", "Medium"],
    },
    "Bug": {
        "subjects": [
            "Numbers on the report are wrong",
            "Button does nothing when clicked",
            "Data not saving after edit",
            "Duplicate records appearing",
            "Chart shows incorrect totals",
            "Search returns no results for valid query",
        ],
        "bodies": [
            "After I edit a record and save, the change disappears on refresh.",
            "The totals in the monthly chart don't match the raw data.",
            "Clicking 'Submit' does nothing and no error is shown.",
            "We're seeing duplicate rows created for a single action.",
            "Search returns nothing even for records I can see in the list.",
        ],
        "base_priorities": ["Medium", "Medium", "High"],
    },
    "General": {
        "subjects": [
            "How do I get started?",
            "Question about your pricing plans",
            "Do you offer a nonprofit discount?",
            "Where can I find the documentation?",
            "General question about limits",
            "Thanks for the great product",
        ],
        "bodies": [
            "I'm evaluating the product and have a few questions.",
            "Is there a guide for onboarding a new team?",
            "What are the rate limits on the starter plan?",
            "Could you point me to the API docs?",
            "Just wanted to say the new update is great.",
        ],
        "base_priorities": ["Low", "Low", "Medium"],
    },
}

# A fraction of tickets get an urgent phrase spliced in to create Urgent cases.
URGENT_SNIPPETS = [
    "This is urgent — our production system is down.",
    "We have a complete outage and cannot access anything.",
    "Critical: customers are affected right now, please help ASAP.",
    "Possible security breach, need help immediately.",
    "Payment failed for all users — this is an emergency.",
]

# Deliberately ambiguous tickets with weak category signal. Real support
# queues are full of these ("it doesn't work", "help"). They keep the model
# honest: some are misclassified and many land below the confidence threshold,
# which is exactly what should trigger the human-review exception path.
GENERIC_SUBJECTS = [
    "Need help",
    "Question",
    "This isn't working",
    "Issue with my account",
    "Problem",
    "Can you help?",
    "Something is wrong",
    "Follow up",
]
GENERIC_BODIES = [
    "It stopped working and I'm not sure why.",
    "Can someone take a look at this when you get a chance?",
    "Not sure who to contact about this.",
    "This has been happening for a few days now.",
    "Please advise.",
    "Let me know what you need from me.",
]


def _weighted_tier(rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for tier, w in TIER_WEIGHTS.items():
        cum += w
        if r <= cum:
            return tier
    return "Free"


def _contains_urgent(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in URGENT_KEYWORDS)


def generate(rows: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    cats = list(TEMPLATES.keys())
    out: list[dict] = []

    for i in range(1, rows + 1):
        category = rng.choice(cats)
        tpl = TEMPLATES[category]
        tier = _weighted_tier(rng)

        # ~18% of tickets are ambiguous: true category is kept, but the text
        # carries weak signal -> lower confidence, some honest misclassification.
        if rng.random() < 0.18:
            subject = rng.choice(GENERIC_SUBJECTS)
            body = rng.choice(GENERIC_BODIES)
        else:
            subject = rng.choice(tpl["subjects"])
            body = rng.choice(tpl["bodies"]).replace(
                "{num}", str(rng.randint(1000, 9999))
            )

        # ~12% of tickets get an urgent phrase appended.
        if rng.random() < 0.12:
            body = body + " " + rng.choice(URGENT_SNIPPETS)

        # Priority label follows the enforced policy.
        priority = rng.choice(tpl["base_priorities"])
        if _contains_urgent(subject + " " + body):
            priority = "Urgent"
        if tier in VIP_TIERS:
            priority = max_priority(priority, VIP_PRIORITY_FLOOR)

        out.append(
            {
                "ticket_id": f"T-{i:05d}",
                "subject": subject,
                "body": body,
                "customer_tier": tier,
                "category": category,
                "priority": priority,
                "assigned_team": CATEGORY_TO_TEAM[category],
            }
        )
    return out


def write_csv(rows: list[dict], path: str) -> None:
    fields = ["ticket_id", "subject", "body", "customer_tier",
              "category", "priority", "assigned_team"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Generate synthetic tickets.")
    parser.add_argument("--rows", type=int, default=600)
    parser.add_argument("--out", type=str, default=settings.data_csv)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rows = generate(args.rows, seed=args.seed)
    write_csv(rows, args.out)
    print(f"Wrote {len(rows)} synthetic tickets to {args.out}")


if __name__ == "__main__":
    main()
