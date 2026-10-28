# Using the Triage System in Your Business

A practical guide for a small or mid-size team adopting this system. No machine-learning background required — if you can edit a text file and run one command, you can make it fit your business.

---

## 1. What it does, in plain terms

Every incoming support ticket is automatically given three things:

- a **category** (e.g. Billing, Technical, Bug),
- a **priority** (Low → Urgent),
- an **owning team** to handle it,

plus a **confidence score** and a **plain-English reason** for the decision. If the system isn't sure, it puts the ticket in a **Human Review Queue** instead of guessing. Every decision and every correction is recorded so you can audit and improve it over time.

---

## 2. Who does what

| Role | Day-to-day |
|---|---|
| **Support agent** | Opens the console, works the queue top-to-bottom (already sorted by priority), and clicks **override** when the system got one wrong. |
| **Operations lead** | Watches the Metrics tab — volume, how many tickets needed human review, how often agents override the system — and adjusts settings (below). |
| **IT / whoever set it up** | Runs the two services, connects your helpdesk, sets the API key, and retrains when you change categories. |

---

## 3. One-time setup

Follow the **Setup** section in the main [README](../README.md): create the environment, install, generate starter data, train, and run. In day-to-day use you only need the two "Run it" commands:

```bash
# Service 1 — the engine (API)
uvicorn app.api.main:app

# Service 2 — the console your agents use
streamlit run app/ui/streamlit_app.py
```

Agents then just open **http://localhost:8501** in a browser.

> For a real deployment you'd run these on a shared server so the whole team hits one URL. See "What I'd change for production" in the README.

---

## 4. Make it yours — configure for *your* business

All the business rules live in **one file: `app/domain.py`**. You do not need to touch any other code.

### a) Your categories and which team owns each
```python
CATEGORY_TO_TEAM = {
    "Billing": "Billing Team",
    "Technical": "Technical Support",
    # ...rename, add, or remove to match your teams
}
```
`CATEGORIES` just lists the category names — keep it in sync with the keys above.

### b) Words that should always mean "Urgent"
```python
URGENT_KEYWORDS = ["outage", "down", "breach", "charged twice", ...]
```
Add the phrases your customers use for emergencies. Any ticket containing one is forced to **Urgent**, no matter what the model thinks.

### c) Which customers always get priority
```python
VIP_TIERS = {"Enterprise", "VIP"}   # these tiers never drop below...
VIP_PRIORITY_FLOOR = "High"          # ...this priority
```

### d) How cautious the system is
In your `.env` file:
```
TRIAGE_CONFIDENCE_THRESHOLD=0.45
```
Raise it (e.g. `0.6`) to send **more** tickets to human review (safer, more manual work). Lower it to auto-assign more (faster, more risk). The Metrics tab's "review rate" tells you if it's set right.

**After changing categories or teams, retrain** (next section). After only changing keywords, tiers, or the threshold, just restart the services.

---

## 5. Train it on your own tickets

The starter model is trained on generated sample tickets. To make it accurate for *your* business, train it on your real resolved tickets.

1. Export your historical tickets to a CSV with these columns:

   | Column | Meaning |
   |---|---|
   | `ticket_id` | any unique id |
   | `subject` | the ticket subject line |
   | `body` | the ticket description |
   | `customer_tier` | Free / Pro / Enterprise / VIP (or your tiers) |
   | `category` | the correct category (how it was actually handled) |
   | `priority` | the correct priority |
   | `assigned_team` | the team that handled it |

2. Save it as `data/tickets.csv` (replacing the sample file).
3. Retrain:
   ```bash
   python -m scripts.train
   ```
   It prints quality scores on a held-out slice of your data so you can see how well it learned. A few hundred tickets is enough to start; more is better.

> No historical data yet? You can run with the sample model and rely mostly on the urgent-keyword and VIP rules at first, then retrain once you've accumulated real tickets (the system is already saving every decision and correction for exactly this).

---

## 6. Connect your helpdesk (optional)

To triage real tickets automatically, have your helpdesk (Zendesk, Freshdesk, email intake, etc.) send each new ticket to the API:

```bash
curl -X POST http://your-server:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"subject":"...","body":"...","customer_tier":"Enterprise"}'
```

The response contains the category, priority, team, and reasons — which your helpdesk can use to tag and route the ticket.

---

## 7. Keep it secure

- Set an API key so only your systems can submit tickets. In `.env`:
  ```
  TRIAGE_API_KEY=choose-a-long-random-value
  ```
  Then every request must include the header `X-API-Key: <that value>`.
- Keep the `.env` file out of version control (it already is, via `.gitignore`).
- Don't put real customer data in a public copy of this repository.

---

## 8. Where your data lives

- All decisions and corrections are stored in a single file: **`data/triage.db`** (SQLite). Back this up like any other important file.
- The trained model is **`data/model.joblib`** — regenerated any time you retrain, so it doesn't need backing up.

---

## 9. Checking it's healthy

Visit **http://localhost:8000/health** — it reports whether the model is loaded and the database is reachable. Use this in monitoring to get alerted if the service degrades.

---

## 10. Current limits (set expectations)

- Priority is genuinely hard to guess from text alone — the system leans on your **keyword and VIP rules** to guarantee urgent things are caught, not on the model. Tune the keyword list; it's your strongest lever.
- The starter accuracy figures come from generated sample data. Your real numbers will differ — retrain on your tickets and read the scores `scripts.train` prints.
- This is a single-server setup. For high volume or multiple locations, see the production notes in the README.
