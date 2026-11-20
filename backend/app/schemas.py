"""Shapes of the data going in and out of the API (validation happens here)."""
from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class TicketIn(BaseModel):
    subject: Optional[str] = None          # may be empty - description alone is enough
    description: str
    email: Optional[EmailStr] = None  # employees: taken from the login; staff: who the ticket is for
    department: str = "IT"
    name: Optional[str] = None
    source: Literal["web", "email", "api"] = "web"

    @field_validator("subject", "name", "department", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("description", mode="before")
    @classmethod
    def _clean_description(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v or len(v) < 5:
            raise ValueError("description must be at least 5 characters")
        return v


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: int
    ticket_code: Optional[str]
    requester_email: Optional[str]
    subject: Optional[str]
    description: str
    department: Optional[str]
    source: Optional[str]
    category: Optional[str]
    sub_category: Optional[str]
    category_confidence: Optional[float]
    severity: Optional[str]
    severity_confidence: Optional[float]
    priority: Optional[str]
    status: str
    processing_ms: Optional[float]
    created_at: datetime
    user_id: Optional[int] = None
    assigned_to: Optional[int] = None
    assignee_name: Optional[str] = None
    due_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class StatusUpdate(BaseModel):
    status: str
    performed_by: Optional[str] = None  # ignored: the logged-in user is recorded


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: int
    action: str
    performed_by: Optional[str]
    timestamp: datetime


# ---------------- Milestone 2 ----------------
def _match_category(value):
    from .config import CATEGORIES
    v = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    for c in CATEGORIES:
        if c.lower() == v:
            return c
    raise ValueError(f"category must be one of {CATEGORIES}")


class ArticleIn(BaseModel):
    title: str
    category: str
    keywords: Optional[Union[str, list[str]]] = None
    content: str

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v):
        return _match_category(v)

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v or len(v) < 5:
            raise ValueError("title must be at least 5 characters")
        return v

    @field_validator("content", mode="before")
    @classmethod
    def _content(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v or len(v) < 20:
            raise ValueError("content must be at least 20 characters")
        return v

    @field_validator("keywords", mode="after")
    @classmethod
    def _kw(cls, v):
        return ", ".join(v) if isinstance(v, list) else v


class ArticleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    article_id: int
    slug: str
    title: str
    category: Optional[str]
    keywords: Optional[str]


class ArticleOut(ArticleSummary):
    content: str
    created_at: datetime


class ArticleCreated(ArticleOut):
    indexed: bool = False
    index_note: Optional[str] = None


class ResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    response_id: int
    ticket_id: int
    generated_response: str
    confidence_score: Optional[float]
    mode: Optional[str]
    needs_human_review: Optional[bool]
    response_ms: Optional[float]
    sources: Optional[list[Any]]
    steps: Optional[list[Any]]
    articles: Optional[list[Any]]
    trace: Optional[list[Any]]
    generated_at: datetime


# ---------------- Milestone 3: login, users, escalations, feedback ----------------
class LoginIn(BaseModel):
    email: str  # not validated as an address: any existing account may log in
    password: str


class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str
    department: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v or len(v) < 2:
            raise ValueError("name must be at least 2 characters")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    name: Optional[str]
    email: str
    department: Optional[str]
    role: str
    team: Optional[str]
    is_active: Optional[bool]
    created_at: Optional[datetime]
    last_login: Optional[datetime] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Literal["employee", "engineer", "admin"] = "employee"
    team: Optional[str] = None
    department: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[Literal["employee", "engineer", "admin"]] = None
    team: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None  # admin password reset

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        if v is not None and len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class PasswordChange(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class EscalationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    escalation_id: int
    ticket_id: int
    ticket_code: Optional[str]
    ticket_subject: Optional[str]
    ticket_category: Optional[str]
    ticket_severity: Optional[str]
    ticket_priority: Optional[str]
    ticket_status: Optional[str]
    assigned_team: Optional[str]
    assigned_to: Optional[int]
    assignee_name: Optional[str]
    escalation_reason: Optional[str]
    escalated_by: Optional[str]
    status: str
    due_at: Optional[datetime]
    resolution_notes: Optional[str]
    created_at: datetime
    accepted_at: Optional[datetime]
    resolved_at: Optional[datetime]


class AssignIn(BaseModel):
    user_id: int


class NoteIn(BaseModel):
    note: str
    visible_to_user: bool = False

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("note must not be empty")
        return v


class ResolveIn(BaseModel):
    notes: str

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v or len(v) < 3:
            raise ValueError("please describe how the issue was resolved")
        return v


class ReasonIn(BaseModel):
    reason: Optional[str] = None


class FeedbackIn(BaseModel):
    is_resolved: bool
    rating: Optional[int] = None
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def _rating(cls, v):
        if v is not None and not 1 <= v <= 5:
            raise ValueError("rating must be between 1 and 5")
        return v


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: int
    ticket_id: int
    response_id: Optional[int]
    user_id: Optional[int]
    is_resolved: bool
    rating: Optional[int]
    comment: Optional[str]
    created_at: datetime


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: int
    ticket_id: int
    agent_name: Optional[str]
    status: Optional[str]
    duration_ms: Optional[float]
    confidence: Optional[float]
    output: Optional[Any]
    created_at: datetime
