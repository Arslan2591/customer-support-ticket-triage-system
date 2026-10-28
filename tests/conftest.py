"""Shared test fixtures.

Each test gets isolated temp paths (db/model/csv), a freshly trained model,
and — for API tests — a TestClient whose lifespan loads that model. Training
on ~300 synthetic rows takes well under a second.
"""
from __future__ import annotations

import importlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIAGE_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRIAGE_MODEL_PATH", str(tmp_path / "m.joblib"))
    monkeypatch.setenv("TRIAGE_DATA_CSV", str(tmp_path / "tickets.csv"))
    monkeypatch.setenv("TRIAGE_CONFIDENCE_THRESHOLD", "0.45")
    monkeypatch.delenv("TRIAGE_API_KEY", raising=False)
    import app.config as config
    config.get_settings.cache_clear()
    return config.get_settings()


@pytest.fixture
def trained_model(env):
    from app.services.model import TriageModel
    from app.services.preprocessing import combine
    from data.generate_data import generate, write_csv

    write_csv(generate(300, seed=3), env.data_csv)
    df = pd.read_csv(env.data_csv).fillna("")
    texts = [combine(s, b) for s, b in zip(df["subject"], df["body"])]
    model = TriageModel.train(texts, df["category"].tolist(), df["priority"].tolist())
    model.save(env.model_path)
    return model


@pytest.fixture
def service(trained_model, env):
    from app.services.triage import TriageService
    return TriageService(trained_model, env.confidence_threshold)


@pytest.fixture
def client(trained_model, env):
    import app.api.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c
