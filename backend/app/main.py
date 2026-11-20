import csv
import io
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from . import access, auth, config, kb, migrate, rag_bridge, security, services, workflow
from .auth import admin_only, get_current_user, staff_only
from .database import SessionLocal, engine, get_db
from .models import (
    ActivityLog, AgentRun, Escalation, Feedback, KnowledgeArticle, Ticket, User,
)
from .schemas import (
    AgentRunOut, ArticleCreated, ArticleIn, ArticleOut, ArticleSummary, AssignIn, EscalationOut, FeedbackIn,
    FeedbackOut, LogOut, LoginIn, NoteIn, PasswordChange, ReasonIn, RegisterIn, ResolveIn, ResponseOut,
    StatusUpdate, TicketIn, TicketOut, TokenOut, UserCreate, UserOut, UserUpdate,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        changes = migrate.run(engine)  # creates missing tables AND adds missing columns
    except OperationalError as exc:
        print("\n*** Could not connect to PostgreSQL. ***")
        print("Is the database running?  Try:  docker compose up -d   (see README)\n")
        raise exc
    if changes:
        print("[migrate] " + "; ".join(changes))
    try:
        with SessionLocal() as db:
            created = auth.seed_default_users(db)
        if created:
            print(f"[auth] created {len(created)} default accounts (admin: {config.ADMIN_EMAIL}). "
                  "Change these passwords before deploying!")
    except Exception as exc:
        print(f"[auth] could not create default accounts: {exc}")
    if config.AUTH_DISABLED:
        print("[auth] WARNING: AUTH_DISABLED is on - every request acts as an admin. Development only!")
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
    description="Ticket intake, AI classification and resolution, escalation to human teams, "
                "login with roles (employee / engineer / admin).",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ helpers
def _name(user: User) -> str:
    return user.name or user.email


def _visible_ticket(db: Session, user: User, ticket_id: int) -> Ticket:
    """The ticket if this user may see it, else 404 (we do not reveal that it exists)."""
    ticket = db.get(Ticket, ticket_id)
    if not ticket or not access.can_view_ticket(db, user, ticket):
        raise HTTPException(404, "Ticket not found")
    return ticket


def _manageable_escalation(db: Session, user: User, escalation_id: int) -> Escalation:
    esc = db.get(Escalation, escalation_id)
    if not esc or not access.can_manage_escalation(user, esc):
        raise HTTPException(404, "Escalation not found")
    return esc


def _bad_request(db: Session, exc: Exception):
    db.rollback()
    raise HTTPException(400, str(exc))


@app.get("/health")
def health():
    return {"status": "ok"}


# ===================================================================
# Login and users
# ===================================================================
def _token_response(user: User) -> dict:
    token, expires_in = security.create_token(user)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "user": user}


@app.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email.lower()).first()
    if not user or not security.verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated. Please contact an administrator.")
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@app.post("/auth/register", response_model=TokenOut, status_code=201, tags=["auth"])
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Employees create their own account. An existing employee record without a password (a person who
    submitted tickets before login existed) simply gets its password set."""
    email = data.email.lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        if user.password_hash or user.role != "employee":
            raise HTTPException(409, "An account with this email already exists. Please log in.")
        user.password_hash = security.hash_password(data.password)
        user.name = data.name
        user.department = data.department or user.department
    else:
        user = User(name=data.name, email=email, department=data.department, role="employee", is_active=True,
                    password_hash=security.hash_password(data.password))
        db.add(user)
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@app.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(get_current_user)):
    return user


@app.post("/auth/change-password", tags=["auth"])
def change_password(data: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not security.verify_password(data.old_password, user.password_hash):
        raise HTTPException(400, "The old password is not correct")
    user.password_hash = security.hash_password(data.new_password)
    db.commit()
    return {"changed": True}


@app.get("/teams", tags=["users"])
def teams(user: User = Depends(staff_only)):
    return {"teams": config.TEAMS, "routing_rules": config.ROUTING_RULES, "sla_hours": config.SLA_HOURS,
            "default_team": config.DEFAULT_TEAM}


def _check_team(role: str, team: Optional[str]):
    if team is not None and team not in config.TEAMS:
        raise HTTPException(400, f"team must be one of {config.TEAMS}")
    if role == "engineer" and not team:
        raise HTTPException(400, "an engineer needs a team")


@app.get("/users", response_model=list[UserOut], tags=["users"])
def list_users(
    role: Optional[str] = None,
    team: Optional[str] = None,
    q: Optional[str] = None,
    active: Optional[bool] = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if team:
        query = query.filter(User.team == team)
    if active is not None:
        query = query.filter(User.is_active.is_(active))
    if q:
        query = query.filter(or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    return query.order_by(User.user_id).offset(offset).limit(limit).all()


@app.post("/users", response_model=UserOut, status_code=201, tags=["users"])
def create_user(data: UserCreate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    _check_team(data.role, data.team)
    if db.query(User).filter(User.email == data.email.lower()).first():
        raise HTTPException(409, "A user with this email already exists")
    user = User(name=data.name, email=data.email.lower(), role=data.role, team=data.team,
                department=data.department, is_active=True, password_hash=security.hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.patch("/users/{user_id}", response_model=UserOut, tags=["users"])
def update_user(user_id: int, data: UserUpdate, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    changes = data.model_dump(exclude_unset=True)
    if user.user_id == admin.user_id and (changes.get("is_active") is False or changes.get("role", "admin") != "admin"):
        raise HTTPException(400, "You cannot deactivate or demote your own admin account")
    new_role = changes.get("role", user.role)
    new_team = changes["team"] if "team" in changes else user.team
    _check_team(new_role, new_team)
    password = changes.pop("password", None)
    for key, value in changes.items():
        setattr(user, key, value)
    if password:
        user.password_hash = security.hash_password(password)
    db.commit()
    db.refresh(user)
    return user


# ===================================================================
# Tickets
# ===================================================================
@app.post("/tickets", response_model=TicketOut, status_code=201, tags=["tickets"])
def create_ticket(data: TicketIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Employees always create tickets as themselves. Staff may give another person's email."""
    if user.role == "employee" or not data.email:
        data.email = user.email
        data.name = data.name or user.name
    return services.create_and_classify(db, data)


@app.get("/tickets", response_model=list[TicketOut], tags=["tickets"])
def list_tickets(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    severity: Optional[str] = None,
    assigned_to: Optional[int] = None,
    mine: bool = False,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Employees get their own tickets, engineers their team's and assigned ones, admins everything."""
    query = access.visible_tickets(db, user)
    if mine:
        query = query.filter(Ticket.user_id == user.user_id)
    if status:
        query = query.filter(Ticket.status == status)
    if category:
        query = query.filter(Ticket.category == category)
    if priority:
        query = query.filter(Ticket.priority == priority)
    if severity:
        query = query.filter(Ticket.severity == severity)
    if assigned_to is not None:
        query = query.filter(Ticket.assigned_to == assigned_to)
    if q:
        query = query.filter(or_(Ticket.subject.ilike(f"%{q}%"), Ticket.ticket_code.ilike(f"%{q}%")))
    return query.order_by(Ticket.ticket_id.desc()).offset(offset).limit(limit).all()


@app.post("/tickets/bulk", tags=["tickets"])
async def bulk_upload(file: UploadFile = File(...), admin: User = Depends(admin_only),
                      db: Session = Depends(get_db)):
    """Upload a CSV with columns: subject, description, email (optional: department, name). Admin only."""
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


@app.get("/tickets/{ticket_id}", response_model=TicketOut, tags=["tickets"])
def get_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _visible_ticket(db, user, ticket_id)


@app.get("/tickets/{ticket_id}/history", response_model=list[LogOut], tags=["tickets"])
def ticket_history(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _visible_ticket(db, user, ticket_id)
    return db.query(ActivityLog).filter(ActivityLog.ticket_id == ticket_id).order_by(ActivityLog.log_id).all()


@app.patch("/tickets/{ticket_id}/status", response_model=TicketOut, tags=["tickets"])
def update_status(ticket_id: int, body: StatusUpdate, user: User = Depends(staff_only),
                  db: Session = Depends(get_db)):
    """Staff only. Employees change a ticket's state through feedback (/tickets/{id}/feedback)."""
    ticket = _visible_ticket(db, user, ticket_id)
    try:
        if body.status == "Escalated":
            workflow.escalate(db, ticket, f"Escalated manually by {_name(user)}", by="staff")
            db.refresh(ticket)
            return ticket
        if body.status == "Awaiting User":
            raise ValueError("'Awaiting User' is set automatically when the AI answer is sent")
        return services.change_status(db, ticket, body.status, _name(user))
    except ValueError as exc:
        _bad_request(db, exc)


@app.get("/tickets/{ticket_id}/response", response_model=ResponseOut, tags=["resolution"])
def get_ticket_response(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The latest AI-generated resolution for a ticket."""
    _visible_ticket(db, user, ticket_id)
    row = workflow.latest_response(db, ticket_id)
    if not row:
        raise HTTPException(404, "No response has been generated for this ticket yet")
    return row


@app.post("/tickets/{ticket_id}/resolve", response_model=ResponseOut, tags=["resolution"])
def resolve_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Run the agents again and save a fresh AI answer (does not change the ticket status)."""
    ticket = _visible_ticket(db, user, ticket_id)
    try:
        return services.generate_response(db, ticket, regenerated=True)
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Could not generate a resolution: {exc}")


@app.get("/tickets/{ticket_id}/agent-runs", response_model=list[AgentRunOut], tags=["resolution"])
def ticket_agent_runs(ticket_id: int, user: User = Depends(staff_only), db: Session = Depends(get_db)):
    _visible_ticket(db, user, ticket_id)
    return db.query(AgentRun).filter(AgentRun.ticket_id == ticket_id).order_by(AgentRun.run_id).all()


@app.post("/tickets/{ticket_id}/feedback", response_model=FeedbackOut, status_code=201, tags=["feedback"])
def give_feedback(ticket_id: int, body: FeedbackIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """'Did this fix it?'. Only the person who raised the ticket (or an admin) can answer."""
    ticket = _visible_ticket(db, user, ticket_id)
    if ticket.user_id != user.user_id and user.role != "admin":
        raise HTTPException(403, "Only the person who raised the ticket can give feedback")
    try:
        return workflow.submit_feedback(db, ticket, user, body.is_resolved, body.rating, body.comment)
    except ValueError as exc:
        _bad_request(db, exc)


@app.get("/tickets/{ticket_id}/feedback", response_model=list[FeedbackOut], tags=["feedback"])
def ticket_feedback(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _visible_ticket(db, user, ticket_id)
    return db.query(Feedback).filter(Feedback.ticket_id == ticket_id).order_by(Feedback.feedback_id).all()


@app.post("/tickets/{ticket_id}/escalate", response_model=EscalationOut, status_code=201, tags=["escalation"])
def escalate_ticket(ticket_id: int, body: ReasonIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Ask for a human ('I want to talk to someone'). Employees: their own tickets. Staff: any visible ticket."""
    ticket = _visible_ticket(db, user, ticket_id)
    try:
        return workflow.request_escalation(db, ticket, user, body.reason or "")
    except ValueError as exc:
        _bad_request(db, exc)


@app.get("/tickets/{ticket_id}/escalation", response_model=EscalationOut, tags=["escalation"])
def ticket_escalation(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _visible_ticket(db, user, ticket_id)
    esc = workflow.latest_escalation(db, ticket_id)
    if not esc:
        raise HTTPException(404, "This ticket has not been escalated")
    return esc


@app.post("/tickets/{ticket_id}/reopen", response_model=TicketOut, tags=["tickets"])
def reopen(ticket_id: int, body: ReasonIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = _visible_ticket(db, user, ticket_id)
    try:
        workflow.reopen_ticket(db, ticket, _name(user), body.reason or "Reopened")
    except ValueError as exc:
        _bad_request(db, exc)
    db.refresh(ticket)
    return ticket


# ===================================================================
# Escalation queue (engineers and admins)
# ===================================================================
@app.get("/escalations", response_model=list[EscalationOut], tags=["escalation"])
def list_escalations(
    status: Optional[str] = None,
    team: Optional[str] = None,
    assigned_to: Optional[int] = None,
    unassigned: bool = False,
    mine: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(staff_only),
    db: Session = Depends(get_db),
):
    """Engineers see their team's queue and what is assigned to them. Admins see everything."""
    query = db.query(Escalation)
    if user.role == "engineer":
        conditions = [Escalation.assigned_to == user.user_id]
        if user.team:
            conditions.append(Escalation.assigned_team == user.team)
        query = query.filter(or_(*conditions))
    if status:
        query = query.filter(Escalation.status == status)
    if team:
        query = query.filter(Escalation.assigned_team == team)
    if assigned_to is not None:
        query = query.filter(Escalation.assigned_to == assigned_to)
    if unassigned:
        query = query.filter(Escalation.assigned_to.is_(None))
    if mine:
        query = query.filter(Escalation.assigned_to == user.user_id)
    return query.order_by(Escalation.due_at.asc(), Escalation.escalation_id).offset(offset).limit(limit).all()


@app.get("/escalations/{escalation_id}", response_model=EscalationOut, tags=["escalation"])
def get_escalation(escalation_id: int, user: User = Depends(staff_only), db: Session = Depends(get_db)):
    return _manageable_escalation(db, user, escalation_id)


@app.post("/escalations/{escalation_id}/accept", response_model=EscalationOut, tags=["escalation"])
def accept_escalation(escalation_id: int, user: User = Depends(staff_only), db: Session = Depends(get_db)):
    """The logged-in engineer takes the ticket (it becomes In Progress)."""
    esc = _manageable_escalation(db, user, escalation_id)
    try:
        return workflow.accept_escalation(db, esc, user)
    except ValueError as exc:
        _bad_request(db, exc)


@app.post("/escalations/{escalation_id}/assign", response_model=EscalationOut, tags=["escalation"])
def assign_escalation(escalation_id: int, body: AssignIn, admin: User = Depends(admin_only),
                      db: Session = Depends(get_db)):
    esc = _manageable_escalation(db, admin, escalation_id)
    assignee = db.get(User, body.user_id)
    if not assignee:
        raise HTTPException(404, "User not found")
    try:
        return workflow.assign_escalation(db, esc, assignee, admin)
    except ValueError as exc:
        _bad_request(db, exc)


@app.post("/escalations/{escalation_id}/notes", tags=["escalation"])
def add_note(escalation_id: int, body: NoteIn, user: User = Depends(staff_only), db: Session = Depends(get_db)):
    """Internal note, or (visible_to_user=true) a message that is also emailed to the user."""
    esc = _manageable_escalation(db, user, escalation_id)
    workflow.add_note(db, esc.ticket, user, body.note, body.visible_to_user)
    return {"saved": True}


@app.post("/escalations/{escalation_id}/resolve", response_model=EscalationOut, tags=["escalation"])
def resolve_escalation(escalation_id: int, body: ResolveIn, user: User = Depends(staff_only),
                       db: Session = Depends(get_db)):
    esc = _manageable_escalation(db, user, escalation_id)
    try:
        return workflow.resolve_escalation(db, esc, user, body.notes)
    except ValueError as exc:
        _bad_request(db, exc)


# ===================================================================
# Knowledge base, retrieval and statistics
# ===================================================================
@app.get("/kb/articles", response_model=list[ArticleSummary], tags=["knowledge base"])
def list_articles(
    category: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(KnowledgeArticle)
    if category:
        query = query.filter(KnowledgeArticle.category == category)
    if q:
        query = query.filter(KnowledgeArticle.title.ilike(f"%{q}%"))
    return query.order_by(KnowledgeArticle.category, KnowledgeArticle.title).offset(offset).limit(limit).all()


@app.get("/kb/articles/{article_id}", response_model=ArticleOut, tags=["knowledge base"])
def get_article(article_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    article = db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(404, "Article not found")
    return article


@app.post("/kb/articles", response_model=ArticleCreated, status_code=201, tags=["knowledge base"])
def create_article(data: ArticleIn, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Admin only. Saved as a Markdown file (source of truth), stored in the DB, then indexed."""
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


@app.post("/kb/reindex", tags=["knowledge base"])
def reindex_kb(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Admin only. Re-read data/kb/**/*.md into the database, then rebuild the vector index."""
    loaded = kb.load_articles_from_files(db)
    try:
        index = rag_bridge.reindex(db)
    except Exception as exc:
        index = {"indexed": 0, "source": "error", "note": f"indexing failed: {exc}"}
    return {**loaded, "index": index, "rag_source": rag_bridge.rag_source()}


@app.get("/kb/search", tags=["knowledge base"])
def search_kb(
    q: str = Query(..., min_length=2),
    category: Optional[str] = None,
    top_k: int = Query(3, ge=1, le=10),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if category and category not in config.CATEGORIES:
        raise HTTPException(400, f"category must be one of {config.CATEGORIES}")
    results = rag_bridge.search(db, q, category=category, top_k=top_k)
    return {"query": q, "category": category, "results": results, "rag_source": rag_bridge.rag_source()}


@app.get("/stats", tags=["statistics"])
def stats(user: User = Depends(staff_only), db: Session = Depends(get_db)):
    return services.build_stats(db)


@app.get("/rag/stats", tags=["statistics"])
def rag_stats(user: User = Depends(staff_only), db: Session = Depends(get_db)):
    return services.build_rag_stats(db)
