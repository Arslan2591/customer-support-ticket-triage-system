# Architecture

## System overview

```mermaid
flowchart LR
    subgraph Client
        OP[Operator / Streamlit console]
        SYS[Upstream system<br/>e.g. helpdesk webhook]
    end

    subgraph API[FastAPI service]
        H[/GET /health/]
        T[/POST /triage/]
        F[/POST /feedback/]
        M[/GET /metrics/]
        Q[/GET /queue/]
    end

    subgraph Core[Triage core - pure Python, no web deps]
        PRE[Preprocessing]
        MODEL[TF-IDF + LogisticRegression<br/>category & priority]
        RULES[Rule layer<br/>VIP floor + urgent keywords]
        ROUTE[Routing + low-confidence<br/>human-review gate]
    end

    DB[(SQLite<br/>audit trail + feedback)]
    ART[(model.joblib)]

    SYS -->|ticket JSON| T
    OP -->|submit / override| T
    OP --> F
    OP --> Q
    T --> PRE --> MODEL --> RULES --> ROUTE
    MODEL -. loads .- ART
    ROUTE -->|decision + reasons| T
    T -->|persist decision| DB
    F -->|persist override| DB
    M --> DB
    Q --> DB
```

## Decision pipeline

```mermaid
flowchart TD
    A[Incoming ticket<br/>subject, body, tier] --> B[Combine + normalize text]
    B --> C[Model: predict category + priority<br/>with confidence]
    C --> D{Urgent keyword<br/>present?}
    D -->|yes| E[Force priority = Urgent]
    D -->|no| F[Keep model priority]
    E --> G{VIP / Enterprise?}
    F --> G
    G -->|yes| H[Raise priority to >= High]
    G -->|no| I[Unchanged]
    H --> J{Category confidence<br/>>= threshold?}
    I --> J
    J -->|yes| K[Auto-assign to mapped team]
    J -->|no| L[Route to Human Review Queue]
    K --> M[Return decision + reasons<br/>persist to audit log]
    L --> M
```

## Design principles

- **Core logic is framework-free.** Everything in `app/services/` is pure Python
  with no FastAPI or Streamlit imports, so it is unit-testable in isolation and
  reusable behind any interface.
- **Rules override the model, never the reverse.** The probabilistic model
  proposes; deterministic guardrails (VIP floor, urgent keywords) dispose. This
  is how real triage systems keep safety-critical routing auditable.
- **Low confidence is a first-class outcome.** Below the confidence threshold the
  system withholds auto-assignment and asks a human — a wrong auto-route costs
  more than a short human glance.
- **One table set does triple duty.** The SQLite audit trail is simultaneously
  the explainability record, the feedback/learning loop, and the metrics source.

## Deployment boundaries

```mermaid
flowchart LR
    C[Client / operator] -->|HTTPS| APP[FastAPI app<br/>uvicorn]
    APP --> STORE[(SQLite — swap for Postgres in prod)]
    APP --> MODELART[(model.joblib — swap for model registry)]
    APP -.->|telemetry: logs, correlation IDs| OBS[Log sink]
```
