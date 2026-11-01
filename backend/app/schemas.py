"""Shapes of the data going in and out of the API (validation happens here)."""
from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class TicketIn(BaseModel):
    subject: Optional[str] = None          # may be empty - description alone is enough
    description: str
    email: EmailStr
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


class StatusUpdate(BaseModel):
    status: str
    performed_by: str = "system"


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
