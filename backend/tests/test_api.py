"""Run with:  pytest   (from the backend/ folder). Uses a temporary in-memory
database, so it does NOT need PostgreSQL and never touches your real data."""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)  # no "with": skips the Postgres startup step
    app.dependency_overrides.clear()


GOOD = {
    "subject": "VPN not connecting",
    "description": "Connection timed out since this morning, restarting did not help",
    "email": "john.doe@company.com",
    "department": "IT",
}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_ticket_is_classified_and_logged(client):
    r = client.post("/tickets", json=GOOD)
    assert r.status_code == 201
    t = r.json()
    assert t["status"] == "Classified"
    assert t["ticket_code"].startswith("T-")
    assert t["category"] and t["severity"] and t["priority"]
    assert t["processing_ms"] is not None
    history = client.get(f"/tickets/{t['ticket_id']}/history").json()
    assert len(history) == 3  # created + classified + resolution generated


def test_bad_email_and_empty_description_rejected(client):
    assert client.post("/tickets", json={**GOOD, "email": "not-an-email"}).status_code == 422
    assert client.post("/tickets", json={**GOOD, "description": "  "}).status_code == 422


def test_subject_is_optional(client):
    body = {k: v for k, v in GOOD.items() if k != "subject"}
    assert client.post("/tickets", json=body).status_code == 201


def test_status_lifecycle_and_invalid_jump(client):
    tid = client.post("/tickets", json=GOOD).json()["ticket_id"]
    bad = client.patch(f"/tickets/{tid}/status", json={"status": "Closed"})
    assert bad.status_code == 400
    for nxt in ["In Progress", "Resolved", "Closed"]:
        r = client.patch(f"/tickets/{tid}/status", json={"status": nxt, "performed_by": "agent1"})
        assert r.status_code == 200 and r.json()["status"] == nxt


def test_filters_and_not_found(client):
    client.post("/tickets", json=GOOD)
    assert len(client.get("/tickets", params={"status": "Classified"}).json()) == 1
    assert client.get("/tickets", params={"status": "Closed"}).json() == []
    assert client.get("/tickets/9999").status_code == 404


def test_same_email_reuses_user(client):
    client.post("/tickets", json=GOOD)
    client.post("/tickets", json=GOOD)
    tickets = client.get("/tickets").json()
    assert len(tickets) == 2
    assert tickets[0]["requester_email"] == "john.doe@company.com"


def test_bulk_upload_and_stats(client):
    csv_text = (
        "subject,description,email,department\n"
        "Printer jam,The office printer is jammed again please help,a@x.com,IT\n"
        "Bad row,,b@x.com,IT\n"
        "Wifi slow,Wi-Fi is very slow on the third floor today,c@x.com,HR\n"
    )
    r = client.post("/tickets/bulk", files={"file": ("t.csv", io.BytesIO(csv_text.encode()), "text/csv")})
    assert r.status_code == 200
    assert r.json()["created"] == 2 and r.json()["failed"] == 1
    s = client.get("/stats").json()
    assert s["total_tickets"] == 2 and s["avg_processing_ms"] is not None
