"""Conservative auto-resolution and team-selection policy."""

from __future__ import annotations

from typing import Any


ROUTING = {
    "Network": "Network Team",
    "VPN": "Network Team",
    "Password Reset": "Identity & Access Team",
    "Email": "Messaging Team",
    "Hardware": "Desktop Support Team",
    "Software": "Desktop Support Team",
    "Security": "Security Team",
}


def decide(ticket: dict[str, Any], resolution: dict[str, Any], validation: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    category = str(ticket.get("category") or "Unknown")
    severity = str(ticket.get("severity") or "Unknown")
    confidence = min(float(resolution.get("confidence", 0.0)), float(validation.get("confidence", 0.0)))
    reasons = []
    if category.lower() == "unknown" or not category:
        reasons.append("ticket category is Unknown")
    if severity == "Critical":
        reasons.append("critical severity requires human handling")
    if category == "Security":
        reasons.append("security tickets require human handling")
    if resolution.get("needs_human_review"):
        reasons.append("retrieval or resolution confidence requires review")
    if not validation.get("passed"):
        reasons.append("validation found unsupported or missing troubleshooting steps")
    if confidence < 0.60:
        reasons.append(f"validated confidence {confidence:.2f} is below 0.60")
    if str(diagnosis.get("urgency", "")).lower() in {"critical", "high"}:
        reasons.append(f"diagnosis urgency is {diagnosis['urgency']}")
    team = ROUTING.get(category, "Service Desk")
    return {
        "decision": "escalate" if reasons else "auto_resolve",
        "escalate_to": team if reasons else None,
        "reason": "; ".join(dict.fromkeys(reasons)),
    }
