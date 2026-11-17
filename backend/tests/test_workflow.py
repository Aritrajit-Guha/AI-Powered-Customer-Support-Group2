"""The ticket journey: AI answer or human escalation, routing, engineers, feedback, reopen, stats, migration."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app import agent_bridge, classifier, config, hooks, migrate
from app.models import Escalation, User
from .helpers import PASSWORD, TICKET, agents_result, login, make_user


def classify_as(monkeypatch, category="VPN", severity="High", priority="P2"):
    monkeypatch.setattr(classifier, "classify", lambda s, d, dep: {
        "category": category, "sub_category": "General", "category_confidence": 0.9,
        "severity": severity, "severity_confidence": 0.8, "priority": priority})


def new_ticket(api, headers=None, **over):
    r = api.post("/tickets", json={**TICKET, **over}, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()


def history(api, tid):
    return [h["action"] for h in api.get(f"/tickets/{tid}/history").json()]


# ------------------------------------------------------------------ the decision
def test_confident_answer_goes_to_the_user(api, monkeypatch, events):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    t = new_ticket(api)
    assert t["status"] == "Awaiting User"
    assert api.get(f"/tickets/{t['ticket_id']}/escalation").status_code == 404
    assert api.get(f"/tickets/{t['ticket_id']}/response").json()["mode"] == "extractive"
    runs = api.get(f"/tickets/{t['ticket_id']}/agent-runs").json()
    assert [r["agent_name"] for r in runs] == ["Diagnosis", "Resolution"] and runs[0]["duration_ms"] == 5
    assert [e[0] for e in events] == ["ticket_received", "ai_resolution_sent"]
    assert any("AI resolution sent" in h for h in history(api, t["ticket_id"]))


def test_low_confidence_escalates_to_the_right_team_with_sla(api, monkeypatch, events):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.2, needs_review=True))
    t = new_ticket(api)  # VPN / High / P2
    assert t["status"] == "Escalated"
    esc = api.get(f"/tickets/{t['ticket_id']}/escalation").json()
    assert esc["assigned_team"] == "Network Team" and esc["status"] == "Open" and esc["escalated_by"] == "AI"
    assert "human review" in esc["escalation_reason"]
    due = datetime.fromisoformat(esc["due_at"].replace("Z", "+00:00"))
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    assert abs((due - datetime.now(timezone.utc)) - timedelta(hours=config.SLA_HOURS["P2"])) < timedelta(minutes=2)
    assert t["due_at"] is not None
    assert [e[0] for e in events] == ["ticket_received", "escalated"]
    assert events[1][2]["team"] == "Network Team"


@pytest.mark.parametrize("category,severity,priority,team,hours,why", [
    ("Security", "High", "P2", "Security Team", 8, "always go to a human"),
    ("VPN", "Critical", "P1", "Network Team", 4, "Critical severity"),
])
def test_security_and_critical_always_go_to_a_human(api, monkeypatch, category, severity, priority, team, hours, why):
    classify_as(monkeypatch, category, severity, priority)
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.95))  # the AI is very sure
    t = new_ticket(api)
    assert t["status"] == "Escalated"
    esc = api.get(f"/tickets/{t['ticket_id']}/escalation").json()
    assert esc["assigned_team"] == team and why in esc["escalation_reason"]


def test_unknown_classification_goes_to_the_service_desk(api, monkeypatch):
    monkeypatch.setattr(classifier, "classify", lambda s, d, dep: {"category": "Unknown", "severity": "Unknown",
                                                                   "priority": "P3"})
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    t = new_ticket(api)
    assert t["category"] is None and t["status"] == "Escalated"
    esc = api.get(f"/tickets/{t['ticket_id']}/escalation").json()
    assert esc["assigned_team"] == config.DEFAULT_TEAM and "classification failed" in esc["escalation_reason"]
    assert any("Classification failed" in h for h in history(api, t["ticket_id"]))


def test_agents_crashing_still_gets_a_human(api, monkeypatch):
    def boom(db, ticket):
        raise RuntimeError("gemini is down")
    monkeypatch.setattr(agent_bridge, "run", boom)
    t = new_ticket(api)
    assert t["status"] == "Escalated"
    assert any("Resolution generation failed: gemini is down" in h for h in history(api, t["ticket_id"]))
    assert "Automatic resolution failed" in api.get(f"/tickets/{t['ticket_id']}/escalation").json()["escalation_reason"]


def test_agents_can_suggest_a_team(api, monkeypatch):
    monkeypatch.setattr(agent_bridge, "run", agents_result(decision="escalate", escalate_to="Security Team",
                                                            reason="looks like account takeover"))
    t = new_ticket(api)
    esc = api.get(f"/tickets/{t['ticket_id']}/escalation").json()
    assert esc["assigned_team"] == "Security Team" and "account takeover" in esc["escalation_reason"]
    monkeypatch.setattr(agent_bridge, "run", agents_result(decision="escalate", escalate_to="Made Up Team"))
    t2 = new_ticket(api)  # an unknown team is ignored, the rule table decides
    assert api.get(f"/tickets/{t2['ticket_id']}/escalation").json()["assigned_team"] == "Network Team"


def test_agent_bridge_fallback_decides_from_the_retrieval_flag(api):
    t = new_ticket(api)  # no articles in the test database -> nothing to answer with -> human
    assert t["status"] == "Escalated"
    assert agent_bridge.source() == "built-in-fallback"


def test_notification_or_jira_failures_never_break_ticket_creation(api, session_factory, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("smtp is down")
    monkeypatch.setattr(hooks, "_notifications", SimpleNamespace(notify=broken))
    monkeypatch.setattr(hooks, "_jira", SimpleNamespace(sync_ticket=broken))
    t = new_ticket(api)
    assert t["status"] == "Escalated"


def test_jira_sync_is_triggered_with_a_working_session(api, session_factory, monkeypatch):
    seen = []

    def sync(db, ticket_id):
        seen.append((ticket_id, db.get(Escalation, 1) is not None))
    monkeypatch.setattr(hooks, "_jira", SimpleNamespace(sync_ticket=sync))
    t = new_ticket(api)
    assert seen and seen[-1] == (t["ticket_id"], True)


# ------------------------------------------------------------------ engineers
def test_engineers_are_assigned_by_workload(api, session_factory):
    e1 = make_user(session_factory, "one@company.com", role="engineer", team="Network Team", name="Eng One")
    e2 = make_user(session_factory, "two@company.com", role="engineer", team="Network Team", name="Eng Two")
    make_user(session_factory, "sec@company.com", role="engineer", team="Security Team")
    first, second, third = (new_ticket(api) for _ in range(3))
    assert [first["assigned_to"], second["assigned_to"], third["assigned_to"]] == [e1, e2, e1]
    assert first["assignee_name"] == "Eng One"
    with session_factory() as db:
        assert db.query(Escalation).filter(Escalation.assigned_to.is_(None)).count() == 0


def test_engineer_works_a_ticket_from_queue_to_resolution(api, session_factory, events):
    eng = make_user(session_factory, "eng@company.com", role="engineer", team="Network Team", name="Eng")
    t = new_ticket(api)
    tid = t["ticket_id"]
    esc_id = api.get(f"/tickets/{tid}/escalation").json()["escalation_id"]
    assert api.get(f"/escalations/{esc_id}").json()["ticket_code"] == t["ticket_code"]

    accepted = api.post(f"/escalations/{esc_id}/accept")
    assert accepted.status_code == 200 and accepted.json()["status"] == "In Progress"
    assert api.get(f"/tickets/{tid}").json()["status"] == "In Progress"

    events.clear()
    api.post(f"/escalations/{esc_id}/notes", json={"note": "checked the firewall logs"})
    assert events == []  # internal note: nobody is emailed
    api.post(f"/escalations/{esc_id}/notes", json={"note": "Please restart your laptop", "visible_to_user": True})
    assert events[-1][0] == "status_changed" and events[-1][2]["message"] == "Please restart your laptop"

    resolved = api.post(f"/escalations/{esc_id}/resolve", json={"notes": "Replaced the VPN profile"})
    assert resolved.status_code == 200 and resolved.json()["status"] == "Resolved"
    ticket = api.get(f"/tickets/{tid}").json()
    assert ticket["status"] == "Resolved" and ticket["resolved_at"] is not None
    assert events[-1][0] == "resolved" and events[-1][2]["notes"] == "Replaced the VPN profile"
    log = history(api, tid)
    assert any("Internal note: checked the firewall logs" in h for h in log)
    assert any("Resolved by" in h for h in log)
    # a resolved escalation cannot be resolved or accepted again
    assert api.post(f"/escalations/{esc_id}/resolve", json={"notes": "again"}).status_code == 400
    assert api.post(f"/escalations/{esc_id}/accept").status_code == 400


def test_admin_assigns_but_only_to_staff(api, session_factory, events):
    eng = make_user(session_factory, "eng@company.com", role="engineer", team="Security Team", name="Sam")
    emp = make_user(session_factory, "emp@company.com")
    t = new_ticket(api)  # Network Team has nobody -> waiting in the queue
    esc = api.get(f"/tickets/{t['ticket_id']}/escalation").json()
    assert esc["assigned_to"] is None
    assert len(api.get("/escalations", params={"unassigned": True}).json()) == 1
    assert api.post(f"/escalations/{esc['escalation_id']}/assign", json={"user_id": emp}).status_code == 400
    assert api.post(f"/escalations/{esc['escalation_id']}/assign", json={"user_id": 9999}).status_code == 404
    ok = api.post(f"/escalations/{esc['escalation_id']}/assign", json={"user_id": eng})
    assert ok.status_code == 200 and ok.json()["assignee_name"] == "Sam"
    assert api.get(f"/tickets/{t['ticket_id']}").json()["assigned_to"] == eng
    assert events[-1][0] == "assigned" and events[-1][2]["assignee_email"] == "eng@company.com"


# ------------------------------------------------------------------ feedback and reopen
def test_user_confirms_the_ai_answer_fixed_it(api, monkeypatch, events):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    tid = new_ticket(api)["ticket_id"]
    fb = api.post(f"/tickets/{tid}/feedback", json={"is_resolved": True, "rating": 5, "comment": "thanks"})
    assert fb.status_code == 201 and fb.json()["rating"] == 5 and fb.json()["response_id"] is not None
    t = api.get(f"/tickets/{tid}").json()
    assert t["status"] == "Closed" and t["closed_at"] is not None and t["resolved_at"] is not None
    assert events[-1][0] == "closed"
    assert api.post(f"/tickets/{tid}/feedback", json={"is_resolved": True}).status_code == 400  # already closed
    assert len(api.get(f"/tickets/{tid}/feedback").json()) == 1


def test_user_says_the_ai_answer_did_not_help(api, monkeypatch):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    tid = new_ticket(api)["ticket_id"]
    fb = api.post(f"/tickets/{tid}/feedback", json={"is_resolved": False, "rating": 2, "comment": "still broken"})
    assert fb.status_code == 201
    assert api.get(f"/tickets/{tid}").json()["status"] == "Escalated"
    esc = api.get(f"/tickets/{tid}/escalation").json()
    assert esc["escalated_by"] == "user" and "still broken" in esc["escalation_reason"]


def test_feedback_validation(api, monkeypatch):
    t = new_ticket(api)  # escalated: feedback makes no sense yet
    assert api.post(f"/tickets/{t['ticket_id']}/feedback", json={"is_resolved": True}).status_code == 400
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    tid = new_ticket(api)["ticket_id"]
    assert api.post(f"/tickets/{tid}/feedback", json={"is_resolved": True, "rating": 9}).status_code == 422
    assert api.post(f"/tickets/{tid}/feedback", json={"is_resolved": True, "rating": 0}).status_code == 422


def test_resolved_by_engineer_then_user_reopens_or_closes(api, session_factory):
    make_user(session_factory, "eng@company.com", role="engineer", team="Network Team")
    tid = new_ticket(api)["ticket_id"]
    esc_id = api.get(f"/tickets/{tid}/escalation").json()["escalation_id"]
    api.post(f"/escalations/{esc_id}/resolve", json={"notes": "Replaced the profile"})
    # not fixed after all
    api.post(f"/tickets/{tid}/feedback", json={"is_resolved": False, "comment": "same error"})
    t = api.get(f"/tickets/{tid}").json()
    assert t["status"] == "In Progress" and t["resolved_at"] is None
    esc = api.get(f"/tickets/{tid}/escalation").json()
    assert esc["status"] == "In Progress" and esc["escalation_id"] == esc_id  # the same escalation is reopened
    # fixed this time
    api.post(f"/escalations/{esc_id}/resolve", json={"notes": "Reinstalled the client"})
    api.post(f"/tickets/{tid}/feedback", json={"is_resolved": True, "rating": 4})
    assert api.get(f"/tickets/{tid}").json()["status"] == "Closed"
    assert api.post(f"/tickets/{tid}/reopen", json={"reason": "again"}).status_code == 400  # Closed is final


def test_reopen_endpoint(api, session_factory):
    make_user(session_factory, "eng@company.com", role="engineer", team="Network Team")
    tid = new_ticket(api)["ticket_id"]
    esc_id = api.get(f"/tickets/{tid}/escalation").json()["escalation_id"]
    assert api.post(f"/tickets/{tid}/reopen", json={}).status_code == 400  # not resolved yet
    api.post(f"/escalations/{esc_id}/resolve", json={"notes": "done for now"})
    r = api.post(f"/tickets/{tid}/reopen", json={"reason": "it came back"})
    assert r.status_code == 200 and r.json()["status"] == "In Progress"


# ------------------------------------------------------------------ manual control
def test_a_person_can_ask_for_a_human(api, session_factory, monkeypatch, auth_on):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    make_user(session_factory, "anna@company.com")
    anna = login(api, "anna@company.com")
    tid = new_ticket(api, headers=anna)["ticket_id"]
    assert api.get(f"/tickets/{tid}", headers=anna).json()["status"] == "Awaiting User"
    r = api.post(f"/tickets/{tid}/escalate", json={"reason": "I need to talk to someone"}, headers=anna)
    assert r.status_code == 201 and r.json()["escalated_by"] == "user"
    assert api.get(f"/tickets/{tid}", headers=anna).json()["status"] == "Escalated"
    assert api.post(f"/tickets/{tid}/escalate", json={}, headers=anna).json()["escalation_id"] == r.json()["escalation_id"]


def test_cannot_escalate_a_closed_ticket(api, monkeypatch):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    tid = new_ticket(api)["ticket_id"]
    api.post(f"/tickets/{tid}/feedback", json={"is_resolved": True})
    r = api.post(f"/tickets/{tid}/escalate", json={"reason": "x"})
    assert r.status_code == 400 and "cannot be escalated" in r.json()["detail"]
    assert len(api.get(f"/tickets/{tid}/history").json()) == len(history(api, tid))  # nothing half-written


def test_staff_status_changes_follow_the_lifecycle(api, monkeypatch, events):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    tid = new_ticket(api)["ticket_id"]  # Awaiting User
    assert api.patch(f"/tickets/{tid}/status", json={"status": "Awaiting User"}).status_code == 400
    assert api.patch(f"/tickets/{tid}/status", json={"status": "Closed"}).status_code == 400
    esc = api.patch(f"/tickets/{tid}/status", json={"status": "Escalated"})  # staff escalates manually
    assert esc.status_code == 200 and esc.json()["status"] == "Escalated"
    assert api.get(f"/tickets/{tid}/escalation").json()["escalated_by"] == "staff"
    for nxt in ("In Progress", "Resolved", "Closed"):
        assert api.patch(f"/tickets/{tid}/status", json={"status": nxt}).status_code == 200
    # the escalation followed the ticket
    assert api.get(f"/tickets/{tid}/escalation").json()["status"] == "Resolved"
    assert [e[0] for e in events][-2:] == ["resolved", "closed"]


# ------------------------------------------------------------------ numbers for the dashboard
def test_stats_include_escalations_feedback_and_sla(api, session_factory, monkeypatch):
    monkeypatch.setattr(agent_bridge, "run", agents_result(confidence=0.9))
    a, b = new_ticket(api)["ticket_id"], new_ticket(api)["ticket_id"]
    api.post(f"/tickets/{a}/feedback", json={"is_resolved": True, "rating": 5})
    api.post(f"/tickets/{b}/feedback", json={"is_resolved": False, "rating": 2})  # -> escalated
    with session_factory() as db:  # make that escalation overdue
        esc = db.query(Escalation).first()
        esc.due_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    s = api.get("/stats").json()
    assert s["escalations"]["total"] == 1 and s["escalations"]["open"] == 1
    assert s["escalations"]["sla_breached"] == 1 and s["escalations"]["by_team"] == {"Network Team": 1}
    assert s["feedback"] == {"responses": 2, "fixed_issue": 1, "fixed_issue_pct": 50.0,
                             "avg_rating": 3.5, "satisfaction_pct": 50.0}
    assert s["by_status"] == {"Closed": 1, "Escalated": 1}
    assert s["integrations"]["agents"] == "built-in-fallback"


# ------------------------------------------------------------------ database upgrade
OLD_SCHEMA = [
    "CREATE TABLE users (user_id INTEGER PRIMARY KEY, name VARCHAR(100), email VARCHAR(255) NOT NULL, "
    "department VARCHAR(100), role VARCHAR(50), created_at DATETIME)",
    "CREATE TABLE tickets (ticket_id INTEGER PRIMARY KEY, ticket_code VARCHAR(20), user_id INTEGER NOT NULL, "
    "subject VARCHAR(255), description TEXT NOT NULL, status VARCHAR(20))",
    "INSERT INTO users (user_id, name, email, role) VALUES (1, 'Old User', 'old@company.com', 'employee')",
    "INSERT INTO tickets (ticket_id, user_id, description, status) VALUES (1, 1, 'old ticket text', 'Classified')",
]


def test_migration_upgrades_an_existing_database_and_is_repeatable():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        for statement in OLD_SCHEMA:
            conn.execute(text(statement))
    changes = migrate.run(engine)
    assert "added column users.password_hash" in changes and "added column tickets.assigned_to" in changes
    columns = {c["name"] for c in inspect(engine).get_columns("tickets")}
    assert {"assigned_to", "due_at", "resolved_at", "closed_at", "duplicate_of"} <= columns
    tables = set(inspect(engine).get_table_names())
    assert {"escalations", "jira_tickets", "email_log", "feedback", "agent_runs"} <= tables
    with engine.connect() as conn:  # old data is kept, and existing users are active
        assert conn.execute(text("SELECT is_active FROM users WHERE user_id = 1")).scalar() in (1, True)
        assert conn.execute(text("SELECT description FROM tickets")).scalar() == "old ticket text"
    assert migrate.run(engine) == []  # nothing left to do the second time
