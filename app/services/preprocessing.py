"""Text preprocessing: combine subject/body and normalize missing fields.

Kept tiny and deterministic so the same transform is used at train time and
at inference time (no train/serve skew).
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """Lowercase, collapse whitespace, strip. None/NaN-safe."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    return _WS.sub(" ", text)


def combine(subject: str | None, body: str | None) -> str:
    """Build the single text field the model consumes.

    Subject is repeated once to give it slightly more weight than body text,
    which is a cheap, standard trick for short-text ticket classification.
    """
    subj = clean_text(subject)
    body_clean = clean_text(body)
    return f"{subj} {subj} {body_clean}".strip()
