"""Bridge between the backend and Role B's multi-agent workflow.

Contract (agreed with Role B):

    agents.orchestrator.run(ticket) -> {
        "agent_trace": [{"agent": "Diagnosis", "status": "ok", "ms": 120, "confidence": 0.8, "summary": "..."}, ...],
        "diagnosis":   {...anything useful, stored with the run...},
        "resolution":  {response_text, steps, sources, articles, confidence, mode,
                        needs_human_review, trace, response_ms},      # same shape as rag.pipeline.resolve
        "validation":  {"passed": true, "confidence": 0.8, "notes": "..."},
        "decision":    "auto_resolve" | "escalate",
        "escalate_to": "Network Team" | None,                        # optional suggestion
        "reason":      "why",
    }
    `ticket` is a dict: ticket_id, ticket_code, subject, description, department, category, sub_category,
    severity, priority, category_confidence, severity_confidence.
    The backend saves agent_trace into the agent_runs table - Role B does not write to the database.

If agents/orchestrator.py does not exist yet, the existing retrieval pipeline (rag_bridge) is used and the
decision is made from its own needs_human_review flag.
"""
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from . import rag_bridge
from .hooks import _load

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

_orch = _load("agents.orchestrator")


def source() -> str:
    return "agents-package" if hasattr(_orch, "run") else "built-in-fallback"


def _ticket_dict(ticket) -> dict:
    return {
        "ticket_id": ticket.ticket_id, "ticket_code": ticket.ticket_code,
        "subject": ticket.subject or "", "description": ticket.description,
        "department": ticket.department, "category": ticket.category, "sub_category": ticket.sub_category,
        "severity": ticket.severity, "priority": ticket.priority,
        "category_confidence": ticket.category_confidence, "severity_confidence": ticket.severity_confidence,
    }


def _fallback(db: Session, ticket) -> dict:
    resolution = rag_bridge.resolve(db, ticket.subject or "", ticket.description, ticket.category)
    trace = {t.get("step"): t.get("ms") for t in resolution.get("trace", []) if isinstance(t, dict)}
    return {
        "agent_trace": [
            {"agent": "Retrieval", "status": "ok", "ms": trace.get("Knowledge base retrieval"),
             "confidence": resolution["confidence"], "summary": f"{len(resolution['articles'])} article(s) found"},
            {"agent": "Resolution", "status": "ok", "ms": trace.get("Response generation"),
             "confidence": resolution["confidence"], "summary": f"mode {resolution['mode']}"},
        ],
        "diagnosis": {},
        "resolution": resolution,
        "validation": {"passed": not resolution["needs_human_review"], "confidence": resolution["confidence"],
                       "notes": "built-in fallback (no agents package)"},
        "decision": "escalate" if resolution["needs_human_review"] else "auto_resolve",
        "escalate_to": None,
        "reason": "",
    }


def _normalize(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("agents.orchestrator.run must return a dict")
    resolution = rag_bridge._normalize(raw.get("resolution"))  # also checks response_text and cleans JSON
    decision = raw.get("decision")
    if decision not in ("auto_resolve", "escalate"):
        decision = "escalate" if resolution["needs_human_review"] else "auto_resolve"
    trace = [t for t in (raw.get("agent_trace") or []) if isinstance(t, dict)]
    return rag_bridge._clean({
        "agent_trace": trace,
        "diagnosis": raw.get("diagnosis") or {},
        "resolution": resolution,
        "validation": raw.get("validation") or {},
        "decision": decision,
        "escalate_to": raw.get("escalate_to"),
        "reason": str(raw.get("reason") or ""),
    })


def run(db: Session, ticket) -> dict:
    if hasattr(_orch, "run"):
        return _normalize(_orch.run(_ticket_dict(ticket)))
    return _normalize(_fallback(db, ticket))
