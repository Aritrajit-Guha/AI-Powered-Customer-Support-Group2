"""Who may see or manage what."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Query, Session

from .models import Escalation, Ticket, User


def visible_tickets(db: Session, user: User) -> Query:
    """Tickets this user is allowed to see.
    employee: their own. engineer: assigned to them or escalated to their team. admin: all."""
    q = db.query(Ticket)
    if user.role == "admin":
        return q
    if user.role == "engineer":
        conditions = [Ticket.assigned_to == user.user_id]
        if user.team:
            conditions.append(Ticket.ticket_id.in_(
                select(Escalation.ticket_id).where(Escalation.assigned_team == user.team)))
        return q.filter(or_(*conditions))
    return q.filter(Ticket.user_id == user.user_id)


def can_view_ticket(db: Session, user: User, ticket: Ticket) -> bool:
    return db.query(visible_tickets(db, user).filter(Ticket.ticket_id == ticket.ticket_id).exists()).scalar()


def can_manage_escalation(user: User, escalation: Escalation) -> bool:
    if user.role == "admin":
        return True
    if user.role != "engineer":
        return False
    return escalation.assigned_to == user.user_id or (bool(user.team) and escalation.assigned_team == user.team)
