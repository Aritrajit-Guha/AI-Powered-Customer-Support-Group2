from app import agent_bridge

from .helpers import TICKET


def test_diagnosis_and_validation_outputs_are_persisted(api, monkeypatch):
    diagnosis = {
        "summary": "VPN connectivity problem",
        "suspected_cause": "stale VPN session",
        "missing_information": [],
        "urgency": "medium",
        "confidence": 0.84,
    }
    validation = {"passed": True, "confidence": 0.81, "notes": "Grounded"}

    def run(db, ticket):
        return {
            "agent_trace": [
                {"agent": "Diagnosis", "status": "ok", "ms": 3, "confidence": 0.84,
                 "summary": diagnosis["summary"], "output": diagnosis},
                {"agent": "Validation", "status": "ok", "ms": 2, "confidence": 0.81,
                 "summary": validation["notes"], "output": validation},
            ],
            "diagnosis": diagnosis,
            "validation": validation,
            "resolution": {
                "response_text": "Try these steps.", "steps": ["a"], "sources": [], "articles": [],
                "confidence": 0.81, "mode": "extractive", "needs_human_review": False,
                "trace": [], "response_ms": 5,
            },
            "decision": "auto_resolve", "escalate_to": None, "reason": "",
        }

    monkeypatch.setattr(agent_bridge, "run", run)
    ticket = api.post("/tickets", json=TICKET).json()
    runs = api.get(f"/tickets/{ticket['ticket_id']}/agent-runs").json()
    assert runs[0]["output"] == diagnosis
    assert runs[1]["output"] == validation
