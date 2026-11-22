"""Database tables (the PDF schema + the extra columns we agreed on).

Milestone 3 added: users (login + team), tickets (assignment + SLA), and the
tables escalations, jira_tickets, email_log, feedback, agent_runs.
`app/migrate.py` adds any missing column/table to an existing database.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String(255), unique=True, nullable=False, index=True)
    department = Column(String(100))
    role = Column(String(50), default="employee")  # employee / engineer / admin
    created_at = Column(DateTime(timezone=True), default=utcnow)
    # --- Milestone 3 ---
    password_hash = Column(String(255))  # empty = account exists but cannot log in yet
    is_active = Column(Boolean, default=True)
    team = Column(String(100))  # for engineers: which support team they belong to
    last_login = Column(DateTime(timezone=True))

    tickets = relationship("Ticket", foreign_keys="Ticket.user_id", back_populates="user")


class Ticket(Base):
    __tablename__ = "tickets"

    ticket_id = Column(Integer, primary_key=True)
    ticket_code = Column(String(20), unique=True, index=True)  # e.g. T-2026-0001
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    subject = Column(String(255))
    description = Column(Text, nullable=False)
    department = Column(String(100))
    source = Column(String(20), default="web")  # web / email / api

    category = Column(String(50))
    sub_category = Column(String(80))
    category_confidence = Column(Float)
    severity = Column(String(20))
    severity_confidence = Column(Float)
    priority = Column(String(5))

    status = Column(String(20), default="Open", index=True)
    processing_ms = Column(Float)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    # --- Milestone 3 ---
    assigned_to = Column(Integer, ForeignKey("users.user_id"))  # the engineer working on it
    due_at = Column(DateTime(timezone=True))  # SLA deadline
    resolved_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    duplicate_of = Column(Integer, ForeignKey("tickets.ticket_id"))  # reserved (duplicate detection, later)

    user = relationship("User", foreign_keys=[user_id], back_populates="tickets")
    assignee = relationship("User", foreign_keys=[assigned_to])

    @property
    def requester_email(self):
        return self.user.email if self.user else None

    @property
    def assignee_name(self):
        return self.assignee.name if self.assignee else None

    logs = relationship("ActivityLog", back_populates="ticket", order_by="ActivityLog.log_id")
    responses = relationship("TicketResponse", back_populates="ticket", order_by="TicketResponse.response_id")
    escalations = relationship("Escalation", back_populates="ticket", order_by="Escalation.escalation_id")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    log_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.ticket_id"), nullable=False, index=True)
    action = Column(String(500))
    performed_by = Column(String(100))
    timestamp = Column(DateTime(timezone=True), default=utcnow)

    ticket = relationship("Ticket", back_populates="logs")


class KnowledgeArticle(Base):
    """PDF table: Knowledge_Base. One row per article file in data/kb/."""
    __tablename__ = "knowledge_base"

    article_id = Column(Integer, primary_key=True)
    slug = Column(String(150), unique=True, nullable=False, index=True)  # file name without .md
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(50), index=True)
    keywords = Column(Text)
    embedding_id = Column(Integer)  # PDF column; we use article_id as the vector id
    created_at = Column(DateTime(timezone=True), default=utcnow)


class TicketResponse(Base):
    """PDF table: Ticket_Responses. One row per generated answer (a ticket can have several)."""
    __tablename__ = "ticket_responses"

    response_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.ticket_id"), nullable=False, index=True)
    generated_response = Column(Text, nullable=False)
    confidence_score = Column(Float)
    generated_at = Column(DateTime(timezone=True), default=utcnow)
    sources = Column(JSON)   # [{slug, title, score}]
    steps = Column(JSON)     # ["Step one", ...]
    articles = Column(JSON)  # everything retrieved (for the UI)
    trace = Column(JSON)     # [{step, ms}] the 4 RAG steps
    mode = Column(String(20))  # stub / extractive / llm ...
    needs_human_review = Column(Boolean, default=False)
    response_ms = Column(Float)

    ticket = relationship("Ticket", back_populates="responses")


# ------------------------------------------------------------------ Milestone 3 tables
class Escalation(Base):
    """PDF table: Escalations. A ticket handed to a human support team."""
    __tablename__ = "escalations"

    escalation_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.ticket_id"), nullable=False, index=True)
    assigned_team = Column(String(100))
    assigned_to = Column(Integer, ForeignKey("users.user_id"))  # engineer (can be empty = waiting in the queue)
    escalation_reason = Column(Text)
    escalated_by = Column(String(50))  # AI / user / staff
    status = Column(String(20), default="Open", index=True)  # Open / In Progress / Resolved
    due_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    accepted_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))

    ticket = relationship("Ticket", back_populates="escalations")
    assignee = relationship("User", foreign_keys=[assigned_to])

    # handy read-only fields so the queue screen needs no extra calls
    @property
    def ticket_code(self):
        return self.ticket.ticket_code if self.ticket else None

    @property
    def ticket_subject(self):
        return self.ticket.subject if self.ticket else None

    @property
    def ticket_category(self):
        return self.ticket.category if self.ticket else None

    @property
    def ticket_severity(self):
        return self.ticket.severity if self.ticket else None

    @property
    def ticket_priority(self):
        return self.ticket.priority if self.ticket else None

    @property
    def ticket_status(self):
        return self.ticket.status if self.ticket else None

    @property
    def assignee_name(self):
        return self.assignee.name if self.assignee else None


class JiraTicket(Base):
    """PDF table: Jira_Tickets. Written by Role C's Jira integration."""
    __tablename__ = "jira_tickets"

    jira_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.ticket_id"), nullable=False, index=True)
    jira_issue_key = Column(String(50))
    jira_status = Column(String(50))
    jira_url = Column(String(500))
    last_updated = Column(DateTime(timezone=True), default=utcnow)


class EmailLog(Base):
    """Every email the system sends (or would send in dry-run mode). Written by Role C."""
    __tablename__ = "email_log"

    email_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.ticket_id"), index=True)
    to_email = Column(String(255))
    template = Column(String(50))
    subject = Column(String(255))
    status = Column(String(20))  # sent / failed / dry_run
    error = Column(Text)
    sent_at = Column(DateTime(timezone=True), default=utcnow)


class Feedback(Base):
    """The user's answer to 'Did this fix it?' (also the source of the satisfaction score)."""
    __tablename__ = "feedback"

    feedback_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.ticket_id"), nullable=False, index=True)
    response_id = Column(Integer, ForeignKey("ticket_responses.response_id"))
    user_id = Column(Integer, ForeignKey("users.user_id"))
    is_resolved = Column(Boolean, nullable=False)
    rating = Column(Integer)  # 1..5, optional
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class AgentRun(Base):
    """One row per agent step of the multi-agent workflow (Role B returns it, the backend saves it)."""
    __tablename__ = "agent_runs"

    run_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.ticket_id"), nullable=False, index=True)
    agent_name = Column(String(50))
    status = Column(String(20))
    duration_ms = Column(Float)
    confidence = Column(Float)
    output = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class RecurringIssue(Base):
    """Aggregated issue signature written by Role B's scheduled detector."""
    __tablename__ = "recurring_issues"

    recurring_issue_id = Column(Integer, primary_key=True)
    signature = Column(String(255), unique=True, nullable=False, index=True)
    category = Column(String(50), index=True)
    assigned_team = Column(String(100))
    occurrence_count = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))
    sample_ticket_ids = Column(JSON)
    status = Column(String(20), default="Open")
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
