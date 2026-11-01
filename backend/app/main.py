import csv
import io
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from . import config, kb, rag_bridge, services
from .database import Base, SessionLocal, engine, get_db
from .models import ActivityLog, KnowledgeArticle, Ticket, TicketResponse
from .schemas import (
    ArticleCreated, ArticleIn, ArticleOut, ArticleSummary, LogOut, ResponseOut,
    StatusUpdate, TicketIn, TicketOut,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(engine)  # creates the 3 tables if they don't exist
    except OperationalError as exc:
        print("\n*** Could not connect to PostgreSQL. ***")
        print("Is the database running?  Try:  docker compose up -d   (see README)\n")
        raise exc
    # keep the Knowledge_Base table in sync with the article files (does not build the vector index)
    try:
        with SessionLocal() as db:
            info = kb.load_articles_from_files(db)
        if info["files_found"]:
            print(f"[kb] {info['files_found']} article files: {info['created']} new, "
                  f"{info['updated']} updated, {len(info['errors'])} problems")
    except Exception as exc:  # never block the API from starting
        print(f"[kb] could not load articles: {exc}")
    yield


app = FastAPI(
    title="SupportPilot API",
    description="Milestone 1: ticket intake, AI classification, lifecycle tracking.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(data: TicketIn, db: Session = Depends(get_db)):
    return services.create_and_classify(db, data)


@app.get("/tickets", response_model=list[TicketOut])
def list_tickets(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Ticket)
    if status:
        q = q.filter(Ticket.status == status)
    if category:
        q = q.filter(Ticket.category == category)
    if priority:
        q = q.filter(Ticket.priority == priority)
    if severity:
        q = q.filter(Ticket.severity == severity)
    return q.order_by(Ticket.ticket_id.desc()).offset(offset).limit(limit).all()


@app.post("/tickets/bulk")
async def bulk_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a CSV with columns: subject, description, email (optional: department, name)."""
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "description" not in reader.fieldnames or "email" not in reader.fieldnames:
        raise HTTPException(400, "CSV must have at least the columns: description, email (subject optional)")

    created, errors = 0, []
    for line_no, row in enumerate(reader, start=2):  # line 1 is the header
        if created + len(errors) >= 5000:
            errors.append({"row": line_no, "error": "stopped: limit of 5000 rows per upload"})
            break
        try:
            data = TicketIn(
                subject=row.get("subject") or None,
                description=row.get("description") or "",
                email=(row.get("email") or "").strip(),
                department=(row.get("department") or "IT"),
                name=row.get("name") or None,
                source="api",
            )
            services.create_and_classify(db, data)
            created += 1
        except ValidationError as exc:
            errors.append({"row": line_no, "error": exc.errors()[0]["msg"]})
    return {"created": created, "failed": len(errors), "errors": errors[:20]}


@app.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@app.get("/tickets/{ticket_id}/history", response_model=list[LogOut])
def ticket_history(ticket_id: int, db: Session = Depends(get_db)):
    if not db.get(Ticket, ticket_id):
        raise HTTPException(404, "Ticket not found")
    return (
        db.query(ActivityLog)
        .filter(ActivityLog.ticket_id == ticket_id)
        .order_by(ActivityLog.log_id)
        .all()
    )


@app.patch("/tickets/{ticket_id}/status", response_model=TicketOut)
def update_status(ticket_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    try:
        return services.change_status(db, ticket, body.status, body.performed_by)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    return services.build_stats(db)


# ===================================================================
# Milestone 2: knowledge base, retrieval and generated resolutions
# ===================================================================
@app.get("/kb/articles", response_model=list[ArticleSummary])
def list_articles(
    category: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeArticle)
    if category:
        query = query.filter(KnowledgeArticle.category == category)
    if q:
        query = query.filter(KnowledgeArticle.title.ilike(f"%{q}%"))
    return query.order_by(KnowledgeArticle.category, KnowledgeArticle.title).offset(offset).limit(limit).all()


@app.get("/kb/articles/{article_id}", response_model=ArticleOut)
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    return article


@app.post("/kb/articles", response_model=ArticleCreated, status_code=201)
def create_article(data: ArticleIn, db: Session = Depends(get_db)):
    """Add an article: saved as a Markdown file (source of truth), stored in the DB, then indexed."""
    slug = kb.unique_slug(db, data.title)
    article = KnowledgeArticle(
        slug=slug, title=data.title, category=data.category, keywords=data.keywords or "", content=data.content
    )
    db.add(article)
    db.flush()
    article.embedding_id = article.article_id
    kb.write_article_file(data.category, slug, data.title, data.keywords or "", data.content)
    db.commit()
    db.refresh(article)

    indexed, note = False, None
    try:
        info = rag_bridge.reindex(db)
        indexed, note = info["indexed"] > 0, info.get("note")
    except Exception as exc:  # the article is saved even if indexing fails
        note = f"saved, but indexing failed: {exc}"
    out = ArticleCreated.model_validate(article)
    out.indexed, out.index_note = indexed, note
    return out


@app.post("/kb/reindex")
def reindex_kb(db: Session = Depends(get_db)):
    """Re-read data/kb/**/*.md into the database, then rebuild the vector index (Role B)."""
    loaded = kb.load_articles_from_files(db)
    try:
        index = rag_bridge.reindex(db)
    except Exception as exc:
        index = {"indexed": 0, "source": "error", "note": f"indexing failed: {exc}"}
    return {**loaded, "index": index, "rag_source": rag_bridge.rag_source()}


@app.get("/kb/search")
def search_kb(
    q: str = Query(..., min_length=2),
    category: Optional[str] = None,
    top_k: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    if category and category not in config.CATEGORIES:
        raise HTTPException(400, f"category must be one of {config.CATEGORIES}")
    results = rag_bridge.search(db, q, category=category, top_k=top_k)
    return {"query": q, "category": category, "results": results, "rag_source": rag_bridge.rag_source()}


@app.get("/tickets/{ticket_id}/response", response_model=ResponseOut)
def get_ticket_response(ticket_id: int, db: Session = Depends(get_db)):
    """The latest generated resolution for a ticket."""
    if not db.get(Ticket, ticket_id):
        raise HTTPException(404, "Ticket not found")
    row = (
        db.query(TicketResponse)
        .filter(TicketResponse.ticket_id == ticket_id)
        .order_by(TicketResponse.response_id.desc())
        .first()
    )
    if not row:
        raise HTTPException(404, "No response has been generated for this ticket yet")
    return row


@app.post("/tickets/{ticket_id}/resolve", response_model=ResponseOut)
def resolve_ticket(ticket_id: int, db: Session = Depends(get_db)):
    """Run retrieval + generation again for an existing ticket."""
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    try:
        return services.generate_response(db, ticket, regenerated=True)
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Could not generate a resolution: {exc}")


@app.get("/rag/stats")
def rag_stats(db: Session = Depends(get_db)):
    return services.build_rag_stats(db)
