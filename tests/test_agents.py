from unittest.mock import patch

from agents.metrics import summarize
from agents.orchestrator import run
from agents.validation import validate


def _resolution(score=0.92, category="VPN"):
    article = {
        "slug": "vpn-timeout",
        "title": "VPN timeout",
        "category": category,
        "score": score,
        "content": "Steps:\n1. Check internet access.\n2. Restart the VPN client.\nEscalate if: it continues.",
    }
    return {
        "response_text": "Based on the article, follow the steps.",
        "steps": ["Check internet access.", "Restart the VPN client."],
        "sources": ["VPN timeout"],
        "articles": [article],
        "confidence": score,
        "mode": "default",
        "needs_human_review": False,
        "trace": [],
        "response_ms": 4,
    }


def test_complex_ticket_has_all_agent_steps_and_auto_resolves():
    ticket = {
        "ticket_id": 1, "subject": "VPN timeout", "description": "VPN connection times out at home",
        "department": "IT", "category": "VPN", "severity": "High", "priority": "P2",
    }
    with patch("agents.orchestrator._safe_resolution", return_value=_resolution()):
        result = run(ticket)
    assert [item["agent"] for item in result["agent_trace"]] == [
        "Diagnosis", "Retrieval", "Resolution", "Validation", "Escalation"
    ]
    assert result["decision"] == "auto_resolve"
    assert all("ms" in item for item in result["agent_trace"])


def test_security_ticket_escalates_with_team_and_reason():
    ticket = {
        "ticket_id": 2, "subject": "Phishing link clicked", "description": "I clicked a suspicious link",
        "department": "IT", "category": "Security", "severity": "High", "priority": "P2",
    }
    with patch("agents.orchestrator._safe_resolution", return_value=_resolution(category="Security")):
        result = run(ticket)
    assert result["decision"] == "escalate"
    assert result["escalate_to"] == "Security Team"
    assert "security" in result["reason"]


def test_junk_ticket_is_safe_and_escalates():
    ticket = {"subject": "hi", "description": "", "category": "Unknown", "severity": "Unknown"}
    with patch("agents.orchestrator._safe_resolution", return_value={
        "response_text": "review", "steps": [], "sources": [], "articles": [], "confidence": 0.0,
        "mode": "human_review", "needs_human_review": True, "trace": [], "response_ms": 1,
    }):
        result = run(ticket)
    assert result["decision"] == "escalate"
    assert result["validation"]["passed"] is False
    assert result["resolution"]["needs_human_review"] is True


def test_validation_reduces_confidence_for_unsupported_steps():
    resolution = _resolution()
    resolution["steps"] = ["Delete all firewall rules immediately."]
    result = validate(resolution)
    assert result["passed"] is False
    assert result["confidence"] < resolution["confidence"]


def test_agent_metrics_report_runs_time_success_and_confidence():
    result = summarize([
        {"agent": "Diagnosis", "ms": 10, "confidence": 0.8, "status": "ok"},
        {"agent": "Diagnosis", "ms": 20, "confidence": 0.6, "status": "review"},
    ])
    assert result["Diagnosis"] == {
        "runs": 2, "average_time_ms": 15.0, "success_rate": 0.5, "average_confidence": 0.7,
    }
