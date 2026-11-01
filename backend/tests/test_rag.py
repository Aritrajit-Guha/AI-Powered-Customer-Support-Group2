"""Milestone 2 tests. Run with:  pytest   (from the backend/ folder).
They use a temporary in-memory database and a temporary KB folder, so they do NOT
need PostgreSQL, the real articles, ChromaDB or any API key."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import classifier, config, rag_bridge
from app.database import Base, get_db
from app.main import app

VPN_ARTICLE = """---
title: VPN connection timed out
category: VPN
keywords: vpn, timeout, connection timed out, cannot connect
---
Symptoms: The VPN client shows "connection timed out".
Likely cause: A blocked port or a stale session.
Steps:
1. Check that your internet connection works.
2. Close the VPN client completely and open it again.
3. Select a different VPN server and connect.
Escalate if: the error continues after trying another network.
"""

PASSWORD_ARTICLE = """---
title: Account locked after too many password attempts
category: Password Reset
keywords: password, locked, account locked, reset password
---
Symptoms: You cannot sign in and the account is locked.
Steps:
1. Wait 15 minutes for the lock to expire.
2. Use the self-service password reset page.
Escalate if: the account is still locked after 30 minutes.
"""


@pytest.fixture()
def kb_dir(tmp_path, monkeypatch):
    (tmp_path / "vpn").mkdir()
    (tmp_path / "vpn" / "vpn-timeout.md").write_text(VPN_ARTICLE, encoding="utf-8")
    (tmp_path / "password-reset").mkdir()
    (tmp_path / "password-reset" / "account-locked.md").write_text(PASSWORD_ARTICLE, encoding="utf-8")
    monkeypatch.setattr(config, "KB_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def client(monkeypatch, kb_dir):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # fixed classifier so tests do not depend on the real model
    monkeypatch.setattr(classifier, "classify", lambda s, d, dep: {
        "category": "VPN", "sub_category": "Timeout", "category_confidence": 0.9,
        "severity": "High", "severity_confidence": 0.8, "priority": "P2"})
    # force the built-in fallback even if rag/ exists in the repo
    monkeypatch.setattr(rag_bridge, "_pipeline", None)
    monkeypatch.setattr(rag_bridge, "_retriever", None)
    yield TestClient(app)
    app.dependency_overrides.clear()


TICKET = {
    "subject": "VPN not connecting",
    "description": "Connection timed out since this morning, restarting did not help",
    "email": "john.doe@company.com",
    "department": "IT",
}


def test_reindex_loads_files_and_reports_bad_ones(client, kb_dir):
    (kb_dir / "vpn" / "bad.md").write_text("---\ntitle: Broken\ncategory: Banana\n---\nbody body body body body", encoding="utf-8")
    r = client.post("/kb/reindex").json()
    assert r["files_found"] == 3 and r["created"] == 2 and r["updated"] == 0
    assert len(r["errors"]) == 1 and "Banana" in r["errors"][0]["error"]
    again = client.post("/kb/reindex").json()
    assert again["created"] == 0 and again["updated"] == 2  # no duplicates
    assert len(client.get("/kb/articles").json()) == 2


def test_list_filter_and_get_article(client):
    client.post("/kb/reindex")
    vpn = client.get("/kb/articles", params={"category": "VPN"}).json()
    assert [a["slug"] for a in vpn] == ["vpn-timeout"]
    full = client.get(f"/kb/articles/{vpn[0]['article_id']}").json()
    assert "Steps:" in full["content"]
    assert client.get("/kb/articles/9999").status_code == 404


def test_search_finds_the_right_article(client):
    client.post("/kb/reindex")
    r = client.get("/kb/search", params={"q": "vpn connection timed out"}).json()
    assert r["results"][0]["slug"] == "vpn-timeout"
    assert r["results"][0]["article_id"] is not None
    only_pw = client.get("/kb/search", params={"q": "vpn connection timed out", "category": "Password Reset"}).json()
    assert all(x["category"] == "Password Reset" for x in only_pw["results"])
    assert client.get("/kb/search", params={"q": "vpn", "category": "Nope"}).status_code == 400


def test_ticket_gets_response_with_sources_and_log(client):
    client.post("/kb/reindex")
    t = client.post("/tickets", json=TICKET).json()
    resp = client.get(f"/tickets/{t['ticket_id']}/response")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"][0]["slug"] == "vpn-timeout"
    assert len(body["steps"]) == 3 and body["mode"] == "stub"
    assert 0 <= body["confidence_score"] <= 1
    assert [x["step"] for x in body["trace"]][0].startswith("Ticket analysis")
    assert len(body["trace"]) == 4
    history = client.get(f"/tickets/{t['ticket_id']}/history").json()
    assert any("Resolution generated" in h["action"] for h in history)


def test_no_match_is_flagged_for_human_review(client):
    client.post("/kb/reindex")
    t = client.post("/tickets", json={**TICKET, "subject": "zzz", "description": "qwerty asdfgh zxcvbn lorem"}).json()
    body = client.get(f"/tickets/{t['ticket_id']}/response").json()
    assert body["needs_human_review"] is True and body["steps"] == [] and body["sources"] == []


def test_unknown_classification_still_gets_a_flagged_response(client, monkeypatch):
    client.post("/kb/reindex")
    monkeypatch.setattr(classifier, "classify", lambda s, d, dep: {"category": "Unknown", "severity": "Unknown", "priority": "P3"})
    t = client.post("/tickets", json=TICKET).json()
    assert t["status"] == "Open"  # not classified
    body = client.get(f"/tickets/{t['ticket_id']}/response").json()
    assert body["needs_human_review"] is True and body["sources"]  # still searched all categories


def test_generation_failure_keeps_the_ticket(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(rag_bridge, "resolve", boom)
    r = client.post("/tickets", json=TICKET)
    assert r.status_code == 201 and r.json()["status"] == "Classified"
    tid = r.json()["ticket_id"]
    assert client.get(f"/tickets/{tid}/response").status_code == 404
    assert any("Resolution generation failed" in h["action"] for h in client.get(f"/tickets/{tid}/history").json())


def test_resolve_regenerates(client):
    client.post("/kb/reindex")
    tid = client.post("/tickets", json=TICKET).json()["ticket_id"]
    first = client.get(f"/tickets/{tid}/response").json()["response_id"]
    r = client.post(f"/tickets/{tid}/resolve")
    assert r.status_code == 200 and r.json()["response_id"] != first
    assert client.post("/tickets/9999/resolve").status_code == 404
    assert client.get("/tickets/9999/response").status_code == 404


def test_real_rag_package_is_used_and_normalised(client, monkeypatch):
    fake_pipeline = SimpleNamespace(resolve=lambda s, d, c: {
        "response_text": "Hi, try this.", "confidence": 1.7, "steps": ["a"], "mode": "extractive",
        "sources": [{"slug": "x", "title": "X", "score": 0.9}]})
    monkeypatch.setattr(rag_bridge, "_pipeline", fake_pipeline)
    tid = client.post("/tickets", json=TICKET).json()["ticket_id"]
    body = client.get(f"/tickets/{tid}/response").json()
    assert body["mode"] == "extractive" and body["confidence_score"] == 1.0  # clamped to 0..1
    assert body["generated_response"] == "Hi, try this."
    assert client.get("/rag/stats").json()["rag_source"]["pipeline"] == "rag-package"


def test_create_article_writes_file_and_is_searchable(client, kb_dir):
    r = client.post("/kb/articles", json={
        "title": "Printer shows offline", "category": "hardware", "keywords": ["printer", "offline"],
        "content": "Steps:\n1. Turn the printer off and on again.\n2. Reconnect it to the network."})
    assert r.status_code == 201
    assert r.json()["category"] == "Hardware" and r.json()["slug"] == "printer-shows-offline"
    assert (kb_dir / "hardware" / "printer-shows-offline.md").exists()
    found = client.get("/kb/search", params={"q": "printer offline"}).json()["results"]
    assert found[0]["slug"] == "printer-shows-offline"
    dup = client.post("/kb/articles", json={"title": "Printer shows offline", "category": "Hardware",
                                            "content": "Steps:\n1. Do something useful here please."}).json()
    assert dup["slug"] == "printer-shows-offline-2"
    assert client.post("/kb/articles", json={"title": "Bad one", "category": "Banana",
                                             "content": "x" * 30}).status_code == 422


def test_rag_stats(client):
    client.post("/kb/reindex")
    client.post("/tickets", json=TICKET)
    s = client.get("/rag/stats").json()
    assert s["kb_articles"] == 2 and s["responses_generated"] == 1
    assert s["articles_by_category"]["VPN"] == 1
    assert s["avg_response_ms"] is not None and s["rag_source"]["retriever"] == "built-in-stub"
