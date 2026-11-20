"""Shared test setup. Every test runs without PostgreSQL, API keys, Pinecone, Gemini, Jira or SMTP."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import agent_bridge, classifier, config, hooks, rag_bridge
from app.database import Base, get_db
from app.main import app


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Defaults for EVERY test: no login needed, integrations run inline, no real rag/agents package."""
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    monkeypatch.setattr(hooks, "SYNC", True)
    monkeypatch.setattr(hooks, "_notifications", None)
    monkeypatch.setattr(hooks, "_jira", None)
    monkeypatch.setattr(agent_bridge, "_orch", None)
    monkeypatch.setattr(rag_bridge, "_pipeline", None)
    monkeypatch.setattr(rag_bridge, "_retriever", None)


@pytest.fixture()
def auth_on(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DISABLED", False)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def api(session_factory, monkeypatch):
    """A test client on a fresh in-memory database, with a fixed classifier (VPN / High / P2)."""
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(hooks, "session_factory", session_factory)
    monkeypatch.setattr(classifier, "classify", lambda s, d, dep: {
        "category": "VPN", "sub_category": "Timeout", "category_confidence": 0.9,
        "severity": "High", "severity_confidence": 0.8, "priority": "P2"})
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def events(monkeypatch):
    """Record every notification the backend fires."""
    seen = []
    monkeypatch.setattr(hooks, "_notifications", SimpleNamespace(
        notify=lambda event, ticket_id, **ctx: seen.append((event, ticket_id, ctx))))
    return seen
