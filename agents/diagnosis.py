"""Ticket diagnosis with an optional Gemini adapter and deterministic fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Any


_RULES = [
    ("security", "possible security incident", "high"),
    ("phishing", "possible phishing or social-engineering attempt", "high"),
    ("malware", "possible malware or endpoint compromise", "high"),
    ("ransomware", "possible ransomware activity", "critical"),
    ("vpn", "VPN connectivity or authentication problem", "medium"),
    ("network", "network connectivity or access problem", "medium"),
    ("password", "password or account-access problem", "medium"),
    ("locked", "account lockout or access problem", "medium"),
    ("email", "email delivery or mailbox problem", "low"),
    ("outlook", "email-client problem", "low"),
    ("printer", "printer or peripheral problem", "low"),
    ("crash", "application stability problem", "medium"),
    ("timeout", "service connectivity or timeout problem", "medium"),
]


def _text(ticket: dict[str, Any]) -> str:
    return " ".join(
        str(ticket.get(key) or "")
        for key in ("subject", "description", "category", "sub_category")
    ).strip()


def _rule_based(ticket: dict[str, Any]) -> dict[str, Any]:
    text = _text(ticket)
    lowered = text.lower()
    matched = [(term, cause, urgency) for term, cause, urgency in _RULES if term in lowered]
    category = str(ticket.get("category") or "Unknown")
    severity = str(ticket.get("severity") or "Unknown")

    if not text or len(re.findall(r"\w+", text)) < 3:
        return {
            "summary": "The ticket does not contain enough information for a reliable diagnosis.",
            "suspected_cause": "insufficient information",
            "missing_information": ["affected service", "symptoms", "exact error or recent change"],
            "urgency": "unknown",
            "confidence": 0.0,
            "mode": "rules",
        }

    term, cause, urgency = matched[0] if matched else (None, "the reported support issue", "unknown")
    if severity == "Critical" or category == "Security":
        urgency = "critical"
    missing = []
    if not re.search(r"error|fail|unable|cannot|not working|issue|problem|timeout|locked", lowered):
        missing.append("exact symptom or error message")
    if not ticket.get("department"):
        missing.append("requester department")

    confidence = 0.82 if matched else 0.45
    if category == "Unknown":
        confidence = min(confidence, 0.35)
    return {
        "summary": f"{category} ticket concerning {cause}.",
        "suspected_cause": cause,
        "missing_information": missing,
        "urgency": urgency,
        "matched_signal": term,
        "confidence": confidence,
        "mode": "rules",
    }


def _gemini(ticket: dict[str, Any]) -> dict[str, Any] | None:
    """Call Gemini only when explicitly enabled; failures fall back to rules."""
    if os.environ.get("AGENT_DIAGNOSIS_MODE", "rules").lower() != "gemini":
        return None
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(
            model=os.environ.get("AGENT_DIAGNOSIS_MODEL", "gemini-2.0-flash"),
            google_api_key=os.environ["GEMINI_API_KEY"],
            temperature=0,
            timeout=float(os.environ.get("AGENT_DIAGNOSIS_TIMEOUT_SECONDS", "2.5")),
            max_retries=0,
        )
        prompt = (
            "Return only valid JSON with keys summary, suspected_cause, "
            "missing_information (array), urgency, confidence. Diagnose this support ticket:\n"
            + json.dumps({k: ticket.get(k) for k in ("subject", "description", "category", "severity", "department")})
        )
        response = model.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(str(item) for item in content)
        data = json.loads(str(content).strip().removeprefix("```json").removesuffix("```").strip())
        if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
            return None
        data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
        data["missing_information"] = list(data.get("missing_information") or [])
        data["mode"] = "gemini"
        return data
    except Exception:
        return None


def diagnose(ticket: dict[str, Any]) -> dict[str, Any]:
    return _gemini(ticket) or _rule_based(ticket)
