"""The ticket journey after classification:

    agents (or the retrieval fallback) -> save the AI answer -> DECIDE
        AI answer is good  -> status "Awaiting User", the user is asked "Did this fix it?"
        needs a human      -> escalation: routed to a team (+ SLA deadline), an engineer is assigned,
                              status "Escalated", email + Jira are triggered in the background
    then: engineer accepts / adds notes / resolves, the user gives feedback, or the ticket is reopened.

Every step is written to the activity log. A failure never leaves a ticket stranded: if the AI side
breaks, the ticket is escalated to a human.
"""
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import agent_bridge, config, hooks, routing, services
from .models import AgentRun, Escalation, Feedback, Ticket, TicketResponse, User


def _now():
    return datetime.now(timezone.utc)


def latest_escalation(db: Session, ticket_id: int):
    return (
        db.query(Escalation).filter(Escalation.ticket_id == ticket_id)
        .order_by(Escalation.escalation_id.desc()).first()
    )


def latest_response(db: Session, ticket_id: int):
    return (
        db.query(TicketResponse).filter(TicketResponse.ticket_id == ticket_id)
        .order_by(TicketResponse.response_id.desc()).first()
    )


def save_agent_runs(db: Session, ticket: Ticket, agent_trace: list):
    for item in agent_trace:
        ms = item.get("ms", item.get("duration_ms"))
        db.add(AgentRun(
            ticket_id=ticket.ticket_id,
            agent_name=str(item.get("agent") or "unknown")[:50],
            status=str(item.get("status") or "ok")[:20],
            duration_ms=float(ms) if isinstance(ms, (int, float)) else None,
            confidence=float(item["confidence"]) if isinstance(item.get("confidence"), (int, float)) else None,
            output=item,
        ))


# ------------------------------------------------------------------ the decision
def decide(ticket: Ticket, result: dict) -> list:
    """Reasons to involve a human. An empty list means the AI answer can go to the user."""
    reasons = []
    resolution = result["resolution"]
    if not ticket.category:
        reasons.append("classification failed or returned Unknown")
    if resolution.get("needs_human_review"):
        reasons.append("AI answer flagged for human review (low confidence or no matching article)")
    elif resolution["confidence"] < config.AUTO_RESOLVE_MIN_CONFIDENCE:
        reasons.append(f"AI confidence {resolution['confidence']:.2f} is below {config.AUTO_RESOLVE_MIN_CONFIDENCE:.2f}")
    if result["decision"] == "escalate":
        if result.get("reason"):
            reasons.append(result["reason"])
        elif not reasons:
            reasons.append("the agents recommended escalation")
    if ticket.category in config.ESCALATE_CATEGORIES:
        reasons.append(f"{ticket.category} tickets always go to a human team")
    if ticket.severity in config.ESCALATE_SEVERITIES:
        reasons.append(f"{ticket.severity} severity needs a human")
    # keep the list tidy (no duplicates, same order)
    return list(dict.fromkeys(reasons))


def run_resolution_flow(db: Session, ticket: Ticket):
    """Called right after classification for every new ticket."""
    try:
        started = time.perf_counter()
        result = agent_bridge.run(db, ticket)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
    except Exception as exc:
        db.rollback()
        services.add_log(db, ticket.ticket_id, f"Resolution generation failed: {exc}", "AI")
        db.commit()
        escalate(db, ticket, f"Automatic resolution failed ({exc})", by="AI")
        return

    services.save_response(db, ticket, result["resolution"], elapsed_ms=elapsed)
    save_agent_runs(db, ticket, result["agent_trace"])
    db.commit()

    reasons = decide(ticket, result)
    if reasons:
        escalate(db, ticket, "; ".join(reasons), by="AI", suggested_team=result.get("escalate_to"))
    else:
        mark_awaiting_user(db, ticket, result["resolution"])


def mark_awaiting_user(db: Session, ticket: Ticket, resolution: dict):
    services.change_status(db, ticket, "Awaiting User", "AI", notify=False)
    services.add_log(
        db, ticket.ticket_id,
        f"AI resolution sent to the user (confidence {resolution['confidence']:.2f}) - waiting for confirmation", "AI")
    db.commit()
    hooks.fire_notify("ai_resolution_sent", ticket.ticket_id, confidence=resolution["confidence"])
    hooks.fire_jira_sync(ticket.ticket_id)


# ------------------------------------------------------------------ escalation
def _create_escalation(db: Session, ticket: Ticket, reason: str, by: str, suggested_team=None,
                       status: str = "Open") -> Escalation:
    route = routing.route_ticket(ticket.category, ticket.priority, suggested_team)
    engineer = routing.pick_engineer(db, route["team"])
    esc = Escalation(
        ticket_id=ticket.ticket_id, assigned_team=route["team"], escalation_reason=reason, escalated_by=by,
        status=status, due_at=route["due_at"], assigned_to=engineer.user_id if engineer else None,
        accepted_at=_now() if status == "In Progress" else None,
    )
    db.add(esc)
    ticket.due_at = route["due_at"]
    ticket.assigned_to = engineer.user_id if engineer else None
    db.flush()
    services.add_log(
        db, ticket.ticket_id,
        f"Escalated to {route['team']} (SLA {route['sla_hours']}h): {reason}", by)
    if engineer:
        services.add_log(db, ticket.ticket_id, f"Assigned to {engineer.name}", "system")
    return esc


def escalate(db: Session, ticket: Ticket, reason: str, by: str = "AI", suggested_team=None) -> Escalation:
    """Hand a ticket to a human team. Returns the existing open escalation if there already is one."""
    existing = latest_escalation(db, ticket.ticket_id)
    if existing and existing.status in ("Open", "In Progress") and ticket.status in ("Escalated", "In Progress"):
        return existing
    if "Escalated" not in config.ALLOWED_TRANSITIONS.get(ticket.status, []):
        raise ValueError(f"A ticket that is '{ticket.status}' cannot be escalated")
    esc = _create_escalation(db, ticket, reason, by, suggested_team)
    services.change_status(db, ticket, "Escalated", by, notify=False)  # raises if the status does not allow it
    db.commit()
    db.refresh(esc)
    hooks.fire_notify("escalated", ticket.ticket_id, team=esc.assigned_team, reason=reason,
                      escalation_id=esc.escalation_id, due_at=esc.due_at.isoformat() if esc.due_at else None)
    if esc.assignee:
        hooks.fire_notify("assigned", ticket.ticket_id, assignee_name=esc.assignee.name,
                          assignee_email=esc.assignee.email, team=esc.assigned_team)
    hooks.fire_jira_sync(ticket.ticket_id)
    return esc


def assign_escalation(db: Session, esc: Escalation, assignee: User, performed_by: User) -> Escalation:
    if assignee.role not in config.STAFF_ROLES or not assignee.is_active:
        raise ValueError("Tickets can only be assigned to active engineers or admins")
    esc.assigned_to = assignee.user_id
    esc.ticket.assigned_to = assignee.user_id
    services.add_log(db, esc.ticket_id, f"Assigned to {assignee.name}", performed_by.name or performed_by.email)
    db.commit()
    hooks.fire_notify("assigned", esc.ticket_id, assignee_name=assignee.name, assignee_email=assignee.email,
                      team=esc.assigned_team)
    hooks.fire_jira_sync(esc.ticket_id)
    return esc


def accept_escalation(db: Session, esc: Escalation, user: User) -> Escalation:
    """The engineer takes the ticket: escalation and ticket move to In Progress."""
    if esc.status == "Resolved":
        raise ValueError("This escalation is already resolved")
    ticket = esc.ticket
    esc.assigned_to = user.user_id
    ticket.assigned_to = user.user_id
    esc.status = "In Progress"
    esc.accepted_at = esc.accepted_at or _now()
    if ticket.status == "Escalated":
        services.change_status(db, ticket, "In Progress", user.name or user.email, notify=False)
    services.add_log(db, ticket.ticket_id, f"Accepted by {user.name}", user.name or user.email)
    db.commit()
    hooks.fire_notify("status_changed", ticket.ticket_id, old_status="Escalated", new_status="In Progress",
                      assignee_name=user.name)
    hooks.fire_jira_sync(ticket.ticket_id)
    return esc


def add_note(db: Session, ticket: Ticket, user: User, note: str, visible_to_user: bool = False):
    label = "Message to user" if visible_to_user else "Internal note"
    services.add_log(db, ticket.ticket_id, f"{label}: {note}", user.name or user.email)
    db.commit()
    if visible_to_user:
        hooks.fire_notify("status_changed", ticket.ticket_id, message=note, from_engineer=user.name)


def resolve_escalation(db: Session, esc: Escalation, user: User, notes: str) -> Escalation:
    ticket = esc.ticket
    if esc.status == "Resolved" or ticket.status not in ("Escalated", "In Progress"):
        raise ValueError("Only an open escalation (ticket Escalated or In Progress) can be resolved")
    actor = user.name or user.email
    if ticket.status == "Escalated":
        services.change_status(db, ticket, "In Progress", actor, notify=False)
        esc.accepted_at = esc.accepted_at or _now()
    esc.assigned_to = esc.assigned_to or user.user_id
    ticket.assigned_to = ticket.assigned_to or user.user_id
    esc.resolution_notes = notes
    services.change_status(db, ticket, "Resolved", actor, notify=False)  # also marks the escalation Resolved
    services.add_log(db, ticket.ticket_id, f"Resolved by {user.name}: {notes}", actor)
    db.commit()
    hooks.fire_notify("resolved", ticket.ticket_id, notes=notes, resolved_by=user.name)
    hooks.fire_jira_sync(ticket.ticket_id)
    return esc


def request_escalation(db: Session, ticket: Ticket, user: User, reason: str) -> Escalation:
    """A person asks for a human ('I want to talk to someone')."""
    by = "staff" if user.role in config.STAFF_ROLES else "user"
    return escalate(db, ticket, reason or "A human was requested", by=by)


# ------------------------------------------------------------------ feedback and reopen
def reopen_ticket(db: Session, ticket: Ticket, by: str, reason: str) -> Ticket:
    if ticket.status != "Resolved":
        raise ValueError("Only a Resolved ticket can be reopened (a Closed ticket is final)")
    services.change_status(db, ticket, "In Progress", by, notify=False)
    ticket.resolved_at = None
    esc = latest_escalation(db, ticket.ticket_id)
    if esc:
        esc.status = "In Progress"
        esc.resolved_at = None
    else:
        esc = _create_escalation(db, ticket, reason, "user", status="In Progress")
    services.add_log(db, ticket.ticket_id, f"Reopened: {reason}", by)
    db.commit()
    hooks.fire_notify("status_changed", ticket.ticket_id, old_status="Resolved", new_status="In Progress",
                      message=reason)
    hooks.fire_jira_sync(ticket.ticket_id)
    return ticket


def submit_feedback(db: Session, ticket: Ticket, user: User, is_resolved: bool, rating=None, comment=None) -> Feedback:
    """'Did this fix it?'  yes -> Closed.  no -> a human takes over (escalation, or reopen if already Resolved)."""
    status = ticket.status
    if status not in ("Awaiting User", "Resolved"):
        raise ValueError("Feedback can only be given while the ticket is 'Awaiting User' or 'Resolved'")
    response = latest_response(db, ticket.ticket_id)
    fb = Feedback(ticket_id=ticket.ticket_id, response_id=response.response_id if response else None,
                  user_id=user.user_id, is_resolved=is_resolved, rating=rating, comment=comment)
    db.add(fb)
    actor = f"user:{user.email}"
    verdict = "fixed the issue" if is_resolved else "did not fix the issue"
    services.add_log(db, ticket.ticket_id,
                     f"User feedback: {verdict}" + (f", rating {rating}/5" if rating else ""), actor)
    db.commit()

    if is_resolved:
        if status == "Awaiting User":
            services.change_status(db, ticket, "Resolved", actor, notify=False)
        services.change_status(db, ticket, "Closed", actor, notify=False)
        services.add_log(db, ticket.ticket_id, "Closed - confirmed resolved by the user", actor)
        db.commit()
        hooks.fire_notify("closed", ticket.ticket_id, rating=rating)
        hooks.fire_jira_sync(ticket.ticket_id)
    elif status == "Awaiting User":
        escalate(db, ticket, "The user reported that the AI answer did not fix the issue"
                 + (f": {comment}" if comment else ""), by="user")
    else:
        reopen_ticket(db, ticket, actor, "The user reported that the issue is not resolved"
                      + (f": {comment}" if comment else ""))
    db.refresh(fb)
    return fb
