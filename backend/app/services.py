"""The real work: create a ticket, classify it, log it, change its status."""
import json
import time
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import agent_bridge, classifier, hooks, rag_bridge
from .config import ALLOWED_TRANSITIONS, CATEGORIES, PRIORITIES, RETRIEVAL_METRICS_FILE, SEVERITIES
from .models import ActivityLog, Escalation, Feedback, KnowledgeArticle, Ticket, TicketResponse, User
from .schemas import TicketIn

REQUIRED_KEYS = ["category", "severity", "priority"]


def add_log(db: Session, ticket_id: int, action: str, performed_by: str = "system"):
    db.add(ActivityLog(ticket_id=ticket_id, action=str(action)[:500], performed_by=str(performed_by)[:100]))


def get_or_create_user(db: Session, email: str, department: str, name: str | None) -> User:
    email = email.lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(name=name or email.split("@")[0], email=email, department=department)
    db.add(user)
    db.flush()
    return user


def create_and_classify(db: Session, data: TicketIn) -> Ticket:
    """Save the ticket, run the AI, save the labels, write the log trail."""
    user = get_or_create_user(db, data.email, data.department, data.name)

    ticket = Ticket(
        user_id=user.user_id,
        subject=data.subject,
        description=data.description,
        department=data.department,
        source=data.source,
        status="Open",
    )
    db.add(ticket)
    db.flush()  # gives us ticket.ticket_id
    ticket.ticket_code = f"T-{datetime.now(timezone.utc).year}-{ticket.ticket_id:04d}"
    add_log(db, ticket.ticket_id, f"Ticket created via {data.source}", f"user:{user.email}")
    db.commit()
    hooks.fire_notify("ticket_received", ticket.ticket_id, ticket_code=ticket.ticket_code, email=user.email)

    # --- classification (a failure here must NOT lose the ticket) ---
    try:
        started = time.perf_counter()
        result = classifier.classify(data.subject or "", data.description, data.department)
        elapsed_ms = (time.perf_counter() - started) * 1000

        missing = [k for k in REQUIRED_KEYS if k not in result]
        if missing:
            raise ValueError(f"classifier result is missing keys: {missing}")
        if result["category"] not in CATEGORIES:
            raise ValueError(f"unknown category '{result['category']}'")
        if result["severity"] not in SEVERITIES:
            raise ValueError(f"unknown severity '{result['severity']}'")
        if result["priority"] not in PRIORITIES:
            raise ValueError(f"unknown priority '{result['priority']}'")

        ticket.category = result["category"]
        ticket.sub_category = result.get("sub_category")
        ticket.category_confidence = result.get("category_confidence")
        ticket.severity = result["severity"]
        ticket.severity_confidence = result.get("severity_confidence")
        ticket.priority = result["priority"]
        ticket.processing_ms = round(elapsed_ms, 2)
        ticket.status = "Classified"
        add_log(
            db, ticket.ticket_id,
            f"Classified as {ticket.category} / {ticket.severity} / {ticket.priority}",
            "AI",
        )
    except Exception as exc:  # keep the ticket as Open and record why
        add_log(db, ticket.ticket_id, f"Classification failed: {exc}", "AI")

    db.commit()

    # --- agents + decision: AI answer for the user, or escalation to a human team ---
    try:
        from . import workflow  # imported here to avoid a circular import

        workflow.run_resolution_flow(db, ticket)
    except Exception as exc:  # the ticket must never be lost or left half-done
        db.rollback()
        add_log(db, ticket.ticket_id, f"Automation flow failed: {exc}", "system")
        db.commit()

    db.refresh(ticket)
    return ticket


def save_response(db: Session, ticket: Ticket, resolution: dict, regenerated: bool = False,
                  elapsed_ms=None) -> TicketResponse:
    """Store one generated answer (and log it)."""
    if not ticket.category:  # classification failed or returned "Unknown": a human must look at it
        resolution["needs_human_review"] = True
    row = TicketResponse(
        ticket_id=ticket.ticket_id,
        generated_response=resolution["response_text"],
        confidence_score=resolution["confidence"],
        sources=resolution["sources"],
        steps=resolution["steps"],
        articles=resolution["articles"],
        trace=resolution["trace"],
        mode=resolution["mode"],
        needs_human_review=resolution["needs_human_review"],
        response_ms=elapsed_ms if elapsed_ms is not None else resolution.get("response_ms"),
    )
    db.add(row)
    add_log(
        db, ticket.ticket_id,
        f"Resolution {'regenerated' if regenerated else 'generated'} "
        f"({row.mode}, confidence {row.confidence_score:.2f})"
        + (", needs human review" if row.needs_human_review else ""),
        "AI",
    )
    db.flush()
    return row


def generate_response(db: Session, ticket: Ticket, regenerated: bool = False) -> TicketResponse:
    """Run the agents again for an existing ticket and save the new answer (the ticket status is not changed)."""
    from . import workflow

    started = time.perf_counter()
    result = agent_bridge.run(db, ticket)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    row = save_response(db, ticket, result["resolution"], regenerated, elapsed_ms)
    workflow.save_agent_runs(db, ticket, result["agent_trace"])
    db.commit()
    db.refresh(row)
    return row


def change_status(db: Session, ticket: Ticket, new_status: str, performed_by: str, notify: bool = True):
    allowed = ALLOWED_TRANSITIONS.get(ticket.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Cannot move from '{ticket.status}' to '{new_status}'. "
            f"Allowed next status: {allowed or 'none (ticket is final)'}"
        )
    old = ticket.status
    now = datetime.now(timezone.utc)
    ticket.status = new_status
    if new_status == "Resolved":
        ticket.resolved_at = now
    elif new_status == "Closed":
        ticket.closed_at = now
    # keep the escalation in step with the ticket
    esc = (
        db.query(Escalation).filter(Escalation.ticket_id == ticket.ticket_id)
        .order_by(Escalation.escalation_id.desc()).first()
    )
    if esc:
        if new_status == "In Progress" and esc.status != "Resolved":
            esc.status = "In Progress"
            esc.accepted_at = esc.accepted_at or now
        elif new_status == "Resolved" and esc.status != "Resolved":
            esc.status = "Resolved"
            esc.resolved_at = now
    add_log(db, ticket.ticket_id, f"Status changed: {old} -> {new_status}", performed_by)
    db.commit()
    db.refresh(ticket)
    if notify:
        event = {"Resolved": "resolved", "Closed": "closed"}.get(new_status, "status_changed")
        hooks.fire_notify(event, ticket.ticket_id, old_status=old, new_status=new_status)
        hooks.fire_jira_sync(ticket.ticket_id)
    return ticket


def _counts(db: Session, column):
    rows = db.query(column, func.count(Ticket.ticket_id)).group_by(column).all()
    return {(k or "Unclassified"): v for k, v in rows}


def build_stats(db: Session) -> dict:
    total = db.query(func.count(Ticket.ticket_id)).scalar() or 0
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.query(func.count(Ticket.ticket_id)).filter(Ticket.created_at >= today_start).scalar() or 0
    avg_ms = db.query(func.avg(Ticket.processing_ms)).scalar()
    return {
        "total_tickets": total,
        "tickets_today": today,
        "avg_processing_ms": round(float(avg_ms), 2) if avg_ms is not None else None,
        "by_category": _counts(db, Ticket.category),
        "by_severity": _counts(db, Ticket.severity),
        "by_priority": _counts(db, Ticket.priority),
        "by_status": _counts(db, Ticket.status),
        "classifier_in_use": classifier.classifier_in_use(),
        "escalations": _escalation_summary(db),
        "feedback": _feedback_summary(db),
        "integrations": {**hooks.status(), "agents": agent_bridge.source()},
    }


def build_rag_stats(db: Session) -> dict:
    total = db.query(func.count(TicketResponse.response_id)).scalar() or 0
    review = (
        db.query(func.count(TicketResponse.response_id))
        .filter(TicketResponse.needs_human_review.is_(True))
        .scalar()
        or 0
    )
    avg_conf = db.query(func.avg(TicketResponse.confidence_score)).scalar()
    avg_ms = db.query(func.avg(TicketResponse.response_ms)).scalar()
    by_cat = dict(
        db.query(KnowledgeArticle.category, func.count(KnowledgeArticle.article_id))
        .group_by(KnowledgeArticle.category)
        .all()
    )
    by_mode = dict(db.query(TicketResponse.mode, func.count(TicketResponse.response_id)).group_by(TicketResponse.mode).all())
    metrics = None
    try:
        if RETRIEVAL_METRICS_FILE.exists():
            metrics = json.loads(RETRIEVAL_METRICS_FILE.read_text(encoding="utf-8"))
    except Exception:
        metrics = None
    return {
        "kb_articles": db.query(func.count(KnowledgeArticle.article_id)).scalar() or 0,
        "articles_by_category": by_cat,
        "responses_generated": total,
        "tickets_with_response": db.query(func.count(func.distinct(TicketResponse.ticket_id))).scalar() or 0,
        "needs_human_review": review,
        "needs_human_review_pct": round(100 * review / total, 1) if total else None,
        "avg_confidence": round(float(avg_conf), 3) if avg_conf is not None else None,
        "avg_response_ms": round(float(avg_ms), 2) if avg_ms is not None else None,
        "by_mode": by_mode,
        "rag_source": rag_bridge.rag_source(),
        "retrieval_metrics": metrics,  # e.g. Hit@1 / Hit@3 from Role B's evaluation script
    }


def _escalation_summary(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    open_q = db.query(Escalation).filter(Escalation.status.in_(["Open", "In Progress"]))
    breached = 0
    for e in open_q.all():
        due = e.due_at
        if due is not None:
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            breached += 1 if due < now else 0
    return {
        "total": db.query(func.count(Escalation.escalation_id)).scalar() or 0,
        "open": open_q.count(),
        "unassigned": open_q.filter(Escalation.assigned_to.is_(None)).count(),
        "sla_breached": breached,
        "by_team": dict(db.query(Escalation.assigned_team, func.count(Escalation.escalation_id))
                        .group_by(Escalation.assigned_team).all()),
    }


def _feedback_summary(db: Session) -> dict:
    total = db.query(func.count(Feedback.feedback_id)).scalar() or 0
    resolved = db.query(func.count(Feedback.feedback_id)).filter(Feedback.is_resolved.is_(True)).scalar() or 0
    rated = db.query(func.count(Feedback.feedback_id)).filter(Feedback.rating.isnot(None)).scalar() or 0
    happy = db.query(func.count(Feedback.feedback_id)).filter(Feedback.rating >= 4).scalar() or 0
    avg = db.query(func.avg(Feedback.rating)).scalar()
    return {
        "responses": total,
        "fixed_issue": resolved,
        "fixed_issue_pct": round(100 * resolved / total, 1) if total else None,
        "avg_rating": round(float(avg), 2) if avg is not None else None,
        "satisfaction_pct": round(100 * happy / rated, 1) if rated else None,  # share of ratings 4 or 5
    }
