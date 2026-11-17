from app import models, security

PASSWORD = "Passw0rd!"


def make_user(session_factory, email, role="employee", team=None, password=PASSWORD, name=None, active=True):
    with session_factory() as db:
        user = models.User(name=name or email.split("@")[0], email=email, role=role, team=team, is_active=active,
                           department="IT", password_hash=security.hash_password(password) if password else None)
        db.add(user)
        db.commit()
        return user.user_id


def login(api, email, password=PASSWORD):
    r = api.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def agents_result(confidence=0.9, needs_review=False, decision="auto_resolve", escalate_to=None, reason=""):
    """A fake orchestrator answer, for monkeypatching agent_bridge.run."""
    def run(db, ticket):
        return {
            "agent_trace": [{"agent": "Diagnosis", "status": "ok", "ms": 5, "confidence": 0.8},
                            {"agent": "Resolution", "status": "ok", "ms": 7, "confidence": confidence}],
            "diagnosis": {}, "validation": {"passed": True},
            "resolution": {"response_text": "Try these steps.", "steps": ["a", "b"], "sources": [], "articles": [],
                           "confidence": confidence, "mode": "extractive", "needs_human_review": needs_review,
                           "trace": [], "response_ms": 10},
            "decision": decision, "escalate_to": escalate_to, "reason": reason,
        }
    return run


TICKET = {"subject": "VPN not connecting",
          "description": "Connection timed out since this morning, restarting did not help",
          "department": "IT"}
