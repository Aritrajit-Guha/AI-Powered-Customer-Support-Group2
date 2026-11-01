"""The real work: create a ticket, classify it, log it, change its status."""
import json
import time
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import classifier, rag_bridge
from .config import ALLOWED_TRANSITIONS, CATEGORIES, PRIORITIES, RETRIEVAL_METRICS_FILE, SEVERITIES
from .models import ActivityLog, KnowledgeArticle, Ticket, TicketResponse, User
from .schemas import TicketIn

REQUIRED_KEYS = ["category", "severity", "priority"]


def add_log(db: Session, ticket_id: int, action: str, performed_by: str = "system"):
    db.add(ActivityLog(ticket_id=ticket_id, action=action, performed_by=performed_by))


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

    # --- knowledge retrieval + resolution (a failure here must NOT lose the ticket either) ---
    try:
        generate_response(db, ticket)
    except Exception as exc:
        db.rollback()
        add_log(db, ticket.ticket_id, f"Resolution generation failed: {exc}", "AI")
        db.commit()

    db.refresh(ticket)
    return ticket


def generate_response(db: Session, ticket: Ticket, regenerated: bool = False) -> TicketResponse:
    """Retrieve articles + generate the answer for a ticket, save it, and log it."""
    started = time.perf_counter()
    result = rag_bridge.resolve(db, ticket.subject or "", ticket.description, ticket.category)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    if not ticket.category:  # classification failed or returned "Unknown": a human must look at it
        result["needs_human_review"] = True

    row = TicketResponse(
        ticket_id=ticket.ticket_id,
        generated_response=result["response_text"],
        confidence_score=result["confidence"],
        sources=result["sources"],
        steps=result["steps"],
        articles=result["articles"],
        trace=result["trace"],
        mode=result["mode"],
        needs_human_review=result["needs_human_review"],
        response_ms=elapsed_ms,
    )
    db.add(row)
    add_log(
        db, ticket.ticket_id,
        f"Resolution {'regenerated' if regenerated else 'generated'} "
        f"({row.mode}, confidence {row.confidence_score:.2f})"
        + (", needs human review" if row.needs_human_review else ""),
        "AI",
    )
    db.commit()
    db.refresh(row)
    return row


def change_status(db: Session, ticket: Ticket, new_status: str, performed_by: str):
    allowed = ALLOWED_TRANSITIONS.get(ticket.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Cannot move from '{ticket.status}' to '{new_status}'. "
            f"Allowed next status: {allowed or 'none (ticket is final)'}"
        )
    old = ticket.status
    ticket.status = new_status
    add_log(db, ticket.ticket_id, f"Status changed: {old} -> {new_status}", performed_by)
    db.commit()
    db.refresh(ticket)
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
