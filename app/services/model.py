"""The ML model: two TF-IDF + LogisticRegression classifiers (category and
priority), bundled behind a small, explainable interface.

Why classic ML and not an LLM for this project:
  * trains in <1s on synthetic data, deterministic, no API key, runs in CI;
  * fully explainable — we can surface the exact tokens that drove a
    prediction, which satisfies the "explainable decision path" requirement.

An LLM alternative is discussed in the README's trade-offs section.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.services.preprocessing import combine


@dataclass
class ModelPrediction:
    category: str
    category_confidence: float
    priority: str
    priority_confidence: float
    # Top tokens that pushed the category decision, most influential first.
    top_tokens: list[str] = field(default_factory=list)


def _build_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    min_df=2,
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                ),
            ),
        ]
    )


class TriageModel:
    """Holds the fitted category and priority pipelines."""

    def __init__(self, category_pipe: Pipeline, priority_pipe: Pipeline):
        self.category_pipe = category_pipe
        self.priority_pipe = priority_pipe

    # --- persistence --------------------------------------------------------
    def save(self, path: str) -> None:
        joblib.dump(
            {"category": self.category_pipe, "priority": self.priority_pipe}, path
        )

    @classmethod
    def load(cls, path: str) -> "TriageModel":
        bundle = joblib.load(path)
        return cls(bundle["category"], bundle["priority"])

    # --- training -----------------------------------------------------------
    @classmethod
    def train(
        cls,
        texts: list[str],
        categories: list[str],
        priorities: list[str],
    ) -> "TriageModel":
        cat_pipe = _build_pipeline()
        cat_pipe.fit(texts, categories)
        pri_pipe = _build_pipeline()
        pri_pipe.fit(texts, priorities)
        return cls(cat_pipe, pri_pipe)

    # --- inference ----------------------------------------------------------
    def predict(self, subject: str, body: str) -> ModelPrediction:
        text = combine(subject, body)

        category, cat_conf = self._predict_one(self.category_pipe, text)
        priority, pri_conf = self._predict_one(self.priority_pipe, text)
        tokens = self._explain(self.category_pipe, text, category)

        return ModelPrediction(
            category=category,
            category_confidence=cat_conf,
            priority=priority,
            priority_confidence=pri_conf,
            top_tokens=tokens,
        )

    @staticmethod
    def _predict_one(pipe: Pipeline, text: str) -> tuple[str, float]:
        proba = pipe.predict_proba([text])[0]
        idx = int(np.argmax(proba))
        label = pipe.classes_[idx]
        return str(label), float(proba[idx])

    @staticmethod
    def _explain(pipe: Pipeline, text: str, predicted_label: str, top_n: int = 5) -> list[str]:
        """Return the tokens that contributed most to the predicted class.

        Contribution = tfidf(feature) * model_coefficient(class, feature).
        This is exact for a linear model, not a post-hoc approximation.
        """
        vectorizer: TfidfVectorizer = pipe.named_steps["tfidf"]
        clf: LogisticRegression = pipe.named_steps["clf"]

        row = vectorizer.transform([text])
        if row.nnz == 0:
            return []

        classes = list(clf.classes_)
        if predicted_label not in classes:
            return []
        class_idx = classes.index(predicted_label)
        # Binary LogisticRegression stores a single coef row; handle both.
        coef = clf.coef_[class_idx] if clf.coef_.shape[0] > 1 else clf.coef_[0]

        feature_names = vectorizer.get_feature_names_out()
        contributions: list[tuple[str, float]] = []
        row = row.tocoo()
        for j, v in zip(row.col, row.data):
            contributions.append((feature_names[j], v * coef[j]))

        contributions.sort(key=lambda t: t[1], reverse=True)
        return [name for name, score in contributions[:top_n] if score > 0]
