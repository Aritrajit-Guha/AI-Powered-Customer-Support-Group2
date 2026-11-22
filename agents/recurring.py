"""Recurring-issue detector intended to run from a scheduler or cron job."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


TEAM_BY_CATEGORY = {
    "Network": "Network Team", "VPN": "Network Team",
    "Password Reset": "Identity & Access Team", "Email": "Messaging Team",
    "Hardware": "Desktop Support Team", "Software": "Desktop Support Team",
    "Security": "Security Team",
}


def signature(subject: str, description: str, category: str | None = None) -> str:
    stop = {"the", "and", "for", "with", "this", "that", "please", "help", "issue", "problem"}
    words = [w for w in re.findall(r"[a-z0-9]+", f"{subject} {description}".lower()) if len(w) > 2 and w not in stop]
    return "|".join(([str(category).lower()] if category else []) + sorted(set(words))[:10])


def find_recurring(tickets: Iterable[dict[str, Any]], min_occurrences: int = 3) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ticket in tickets:
        key = signature(ticket.get("subject", ""), ticket.get("description", ""), ticket.get("category"))
        if key:
            groups[key].append(ticket)
    return [
        {"signature": key, "category": str(items[0].get("category") or "Unknown"),
         "occurrence_count": len(items), "sample_ticket_ids": [x.get("ticket_id") for x in items[:5]]}
        for key, items in groups.items() if len(items) >= min_occurrences
    ]


def detect_and_store(db, window_days: int = 30, min_occurrences: int = 3) -> list[dict[str, Any]]:
    """Aggregate recent tickets and upsert recurring issue records."""
    try:
        from backend.app.models import RecurringIssue, Ticket
    except ModuleNotFoundError:
        from app.models import RecurringIssue, Ticket

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    rows = db.query(Ticket).filter(Ticket.created_at >= since).all()
    candidates = find_recurring([
        {"ticket_id": row.ticket_id, "subject": row.subject, "description": row.description,
         "category": row.category, "created_at": row.created_at}
        for row in rows
    ], min_occurrences)
    for item in candidates:
        matching = [row for row in rows if signature(row.subject, row.description, row.category) == item["signature"]]
        times = [row.created_at for row in matching if row.created_at]
        record = db.query(RecurringIssue).filter(RecurringIssue.signature == item["signature"]).first()
        if record is None:
            record = RecurringIssue(signature=item["signature"])
            db.add(record)
        record.category = item["category"]
        record.assigned_team = TEAM_BY_CATEGORY.get(item["category"], "Service Desk")
        record.occurrence_count = item["occurrence_count"]
        record.sample_ticket_ids = item["sample_ticket_ids"]
        record.first_seen = min(times) if times else now
        record.last_seen = max(times) if times else now
        record.status = "Open"
    db.commit()
    return candidates


if __name__ == "__main__":
    try:
        from backend.app.database import SessionLocal
    except ModuleNotFoundError:
        from app.database import SessionLocal

    with SessionLocal() as session:
        print(detect_and_store(session))
