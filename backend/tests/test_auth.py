"""Login, roles and permissions (the login check is switched ON for these tests)."""
import pytest

from app import auth, config
from .helpers import PASSWORD, TICKET, login, make_user

pytestmark = pytest.mark.usefixtures("auth_on")


def test_login_success_and_failures(api, session_factory):
    make_user(session_factory, "anna@company.com")
    make_user(session_factory, "off@company.com", active=False)
    ok = api.post("/auth/login", json={"email": "Anna@Company.com", "password": PASSWORD})  # email is case-insensitive
    assert ok.status_code == 200
    body = ok.json()
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert body["user"]["role"] == "employee" and "password" not in str(body)
    assert api.post("/auth/login", json={"email": "anna@company.com", "password": "wrong-password"}).status_code == 401
    assert api.post("/auth/login", json={"email": "nobody@company.com", "password": PASSWORD}).status_code == 401
    assert api.post("/auth/login", json={"email": "off@company.com", "password": PASSWORD}).status_code == 403


def test_token_is_required_and_checked(api, session_factory, monkeypatch):
    make_user(session_factory, "anna@company.com")
    assert api.get("/tickets").status_code == 401
    assert api.get("/tickets", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert api.get("/health").status_code == 200  # public
    headers = login(api, "anna@company.com")
    me = api.get("/auth/me", headers=headers).json()
    assert me["email"] == "anna@company.com" and me["role"] == "employee"
    monkeypatch.setattr(config, "JWT_EXPIRE_MINUTES", -5)  # a token that is already expired
    expired = login(api, "anna@company.com")
    assert api.get("/auth/me", headers=expired).status_code == 401


def test_deactivated_user_is_locked_out_with_a_valid_token(api, session_factory):
    uid = make_user(session_factory, "anna@company.com")
    admin = make_user(session_factory, "boss@company.com", role="admin")
    anna, boss = login(api, "anna@company.com"), login(api, "boss@company.com")
    assert api.get("/auth/me", headers=anna).status_code == 200
    assert api.patch(f"/users/{uid}", json={"is_active": False}, headers=boss).status_code == 200
    assert api.get("/auth/me", headers=anna).status_code == 401


def test_register_new_duplicate_claim_and_validation(api, session_factory):
    r = api.post("/auth/register", json={"name": "New Person", "email": "new@company.com", "password": "longenough1"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "employee"
    assert api.post("/auth/register", json={"name": "New Person", "email": "new@company.com",
                                            "password": "longenough1"}).status_code == 409
    assert api.post("/auth/register", json={"name": "X Y", "email": "short@company.com",
                                            "password": "short"}).status_code == 422
    # an employee record created before login existed (no password) can claim the account
    make_user(session_factory, "old@company.com", password=None)
    claim = api.post("/auth/register", json={"name": "Old Timer", "email": "old@company.com", "password": "newpassword1"})
    assert claim.status_code == 201
    login(api, "old@company.com", "newpassword1")
    # ... but a staff account without a password can NOT be claimed
    make_user(session_factory, "staff@company.com", role="admin", password=None)
    assert api.post("/auth/register", json={"name": "Hacker", "email": "staff@company.com",
                                            "password": "newpassword1"}).status_code == 409


def test_employee_only_sees_and_creates_own_tickets(api, session_factory):
    make_user(session_factory, "anna@company.com")
    make_user(session_factory, "ben@company.com")
    anna, ben = login(api, "anna@company.com"), login(api, "ben@company.com")
    # Anna tries to file a ticket in Ben's name: it is recorded as hers
    t = api.post("/tickets", json={**TICKET, "email": "ben@company.com"}, headers=anna)
    assert t.status_code == 201 and t.json()["requester_email"] == "anna@company.com"
    tid = t.json()["ticket_id"]
    assert len(api.get("/tickets", headers=anna).json()) == 1
    assert api.get("/tickets", headers=ben).json() == []
    for path in (f"/tickets/{tid}", f"/tickets/{tid}/history", f"/tickets/{tid}/response"):
        assert api.get(path, headers=anna).status_code == 200
        assert api.get(path, headers=ben).status_code == 404  # existence is not revealed
    assert api.post(f"/tickets/{tid}/resolve", headers=ben).status_code == 404
    assert api.post(f"/tickets/{tid}/feedback", json={"is_resolved": True}, headers=ben).status_code == 404


def test_employee_cannot_use_staff_or_admin_endpoints(api, session_factory):
    make_user(session_factory, "anna@company.com")
    anna = login(api, "anna@company.com")
    tid = api.post("/tickets", json=TICKET, headers=anna).json()["ticket_id"]
    assert api.patch(f"/tickets/{tid}/status", json={"status": "In Progress"}, headers=anna).status_code == 403
    assert api.get("/escalations", headers=anna).status_code == 403
    assert api.get("/users", headers=anna).status_code == 403
    assert api.get("/stats", headers=anna).status_code == 403
    assert api.get("/rag/stats", headers=anna).status_code == 403
    assert api.post("/kb/reindex", headers=anna).status_code == 403
    assert api.post("/kb/articles", json={"title": "Some title", "category": "VPN", "content": "x" * 30},
                    headers=anna).status_code == 403
    assert api.post("/tickets/bulk", files={"file": ("t.csv", b"description,email\n")}, headers=anna).status_code == 403
    assert api.get(f"/tickets/{tid}/agent-runs", headers=anna).status_code == 403
    # reading the knowledge base is fine
    assert api.get("/kb/articles", headers=anna).status_code == 200


def test_engineer_sees_only_their_teams_tickets(api, session_factory):
    make_user(session_factory, "anna@company.com")
    make_user(session_factory, "net@company.com", role="engineer", team="Network Team")
    make_user(session_factory, "sec@company.com", role="engineer", team="Security Team")
    anna, net, sec = (login(api, e) for e in ("anna@company.com", "net@company.com", "sec@company.com"))
    tid = api.post("/tickets", json=TICKET, headers=anna).json()["ticket_id"]  # VPN, no KB -> escalated to Network Team
    assert [t["ticket_id"] for t in api.get("/tickets", headers=net).json()] == [tid]
    assert api.get("/tickets", headers=sec).json() == []
    assert api.get(f"/tickets/{tid}", headers=sec).status_code == 404
    assert len(api.get("/escalations", headers=net).json()) == 1
    assert api.get("/escalations", headers=sec).json() == []
    esc_id = api.get("/escalations", headers=net).json()[0]["escalation_id"]
    assert api.post(f"/escalations/{esc_id}/accept", headers=sec).status_code == 404
    assert api.post(f"/escalations/{esc_id}/accept", headers=net).status_code == 200


def test_admin_manages_users(api, session_factory):
    boss_id = make_user(session_factory, "boss@company.com", role="admin")
    boss = login(api, "boss@company.com")
    # an engineer needs a team, and the team must exist
    assert api.post("/users", json={"name": "Eve", "email": "eve@company.com", "password": "longenough1",
                                    "role": "engineer"}, headers=boss).status_code == 400
    assert api.post("/users", json={"name": "Eve", "email": "eve@company.com", "password": "longenough1",
                                    "role": "engineer", "team": "No Such Team"}, headers=boss).status_code == 400
    ok = api.post("/users", json={"name": "Eve", "email": "eve@company.com", "password": "longenough1",
                                  "role": "engineer", "team": "Network Team"}, headers=boss)
    assert ok.status_code == 201 and ok.json()["team"] == "Network Team"
    assert api.post("/users", json={"name": "Eve", "email": "EVE@company.com", "password": "longenough1"},
                    headers=boss).status_code == 409
    login(api, "eve@company.com", "longenough1")
    # change a role, reset a password, list with filters
    uid = ok.json()["user_id"]
    assert api.patch(f"/users/{uid}", json={"password": "resetpass123"}, headers=boss).status_code == 200
    login(api, "eve@company.com", "resetpass123")
    engineers = api.get("/users", params={"role": "engineer"}, headers=boss).json()
    assert [u["email"] for u in engineers] == ["eve@company.com"]
    # an admin cannot lock themselves out
    assert api.patch(f"/users/{boss_id}", json={"is_active": False}, headers=boss).status_code == 400
    assert api.patch(f"/users/{boss_id}", json={"role": "employee"}, headers=boss).status_code == 400
    assert api.patch("/users/9999", json={"name": "x"}, headers=boss).status_code == 404
    assert set(api.get("/teams", headers=boss).json()["teams"]) == set(config.TEAMS)


def test_change_password(api, session_factory):
    make_user(session_factory, "anna@company.com")
    anna = login(api, "anna@company.com")
    assert api.post("/auth/change-password", json={"old_password": "wrong", "new_password": "brandnew123"},
                    headers=anna).status_code == 400
    assert api.post("/auth/change-password", json={"old_password": PASSWORD, "new_password": "brandnew123"},
                    headers=anna).status_code == 200
    login(api, "anna@company.com", "brandnew123")
    assert api.post("/auth/login", json={"email": "anna@company.com", "password": PASSWORD}).status_code == 401


def test_default_accounts_are_created_once(api, session_factory):
    with session_factory() as db:
        created = auth.seed_default_users(db)
        assert len(created) == 1 + len(config.TEAMS)  # admin + one engineer per team
        assert auth.seed_default_users(db) == []  # nothing duplicated
    headers = login(api, config.ADMIN_EMAIL, config.ADMIN_PASSWORD)
    assert api.get("/auth/me", headers=headers).json()["role"] == "admin"
    team = config.TEAMS[0]
    engineer = api.get("/users", params={"role": "engineer", "team": team}, headers=headers).json()
    assert len(engineer) == 1
    login(api, engineer[0]["email"], config.ENGINEER_PASSWORD)


def test_swagger_docs_stay_open(api):
    assert api.get("/docs").status_code == 200
    assert api.get("/openapi.json").status_code == 200
    assert "HTTPBearer" in api.get("/openapi.json").json()["components"]["securitySchemes"]  # the Authorize button
