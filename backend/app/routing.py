"""Routing engine: which team gets an escalated ticket, by when, and which engineer."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import config
from .models import Escalation, User


def route_ticket(category, priority, suggested_team=None) -> dict:
    """Pick the team (rule table, or the agents' suggestion if it is a known team) and the SLA deadline."""
    if suggested_team in config.TEAMS:
        team = suggested_team
    else:
        team = config.ROUTING_RULES.get(category, config.DEFAULT_TEAM)
    hours = config.SLA_HOURS.get(priority, config.SLA_HOURS["P3"])
    return {"team": team, "sla_hours": hours, "due_at": datetime.now(timezone.utc) + timedelta(hours=hours)}


def pick_engineer(db: Session, team: str):
    """The active engineer of that team with the fewest open escalations (None if the team has nobody)."""
    engineers = (
        db.query(User)
        .filter(User.role == "engineer", User.team == team, User.is_active.is_(True))
        .order_by(User.user_id)
        .all()
    )
    if not engineers:
        return None
    load = dict(
        db.query(Escalation.assigned_to, func.count(Escalation.escalation_id))
        .filter(Escalation.status.in_(["Open", "In Progress"]), Escalation.assigned_to.isnot(None))
        .group_by(Escalation.assigned_to)
        .all()
    )
    return min(engineers, key=lambda e: (load.get(e.user_id, 0), e.user_id))
