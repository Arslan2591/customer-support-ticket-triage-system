"""Train the triage model from the labeled CSV and save the artifact.

Run:  python -m scripts.train
      python -m scripts.train --csv data/tickets.csv --out data/model.joblib

Also prints held-out quality metrics so the training run is self-reporting.
"""
from __future__ import annotations

import argparse

import pandas as pd

from app.config import get_settings
from app.services.metrics import evaluate
from app.services.model import TriageModel
from app.services.preprocessing import combine


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Train the triage model.")
    parser.add_argument("--csv", type=str, default=settings.data_csv)
    parser.add_argument("--out", type=str, default=settings.model_path)
    args = parser.parse_args()

    df = pd.read_csv(args.csv).fillna("")
    texts = [combine(s, b) for s, b in zip(df["subject"], df["body"])]

    model = TriageModel.train(
        texts, df["category"].tolist(), df["priority"].tolist()
    )
    model.save(args.out)
    print(f"Trained on {len(df)} tickets -> saved model to {args.out}")

    # Honest, held-out evaluation (simulated portfolio metrics).
    m = evaluate(args.csv, settings.confidence_threshold)
    print("\nHeld-out quality metrics (simulated portfolio metrics):")
    print(f"  test tickets           : {m.n_test}")
    print(f"  category macro F1      : {m.category_macro_f1}")
    print(f"  priority macro F1      : {m.priority_macro_f1}")
    print(f"  routing accuracy       : {m.routing_accuracy}")
    print(f"  high-priority recall   : {m.high_priority_recall}")
    print(f"  auto-containment rate  : {m.auto_containment_rate}")


if __name__ == "__main__":
    main()
