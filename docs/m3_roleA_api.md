# Milestone 3 - backend (Role A): login, workflow, escalation

Run exactly as before (`uvicorn app.main:app --reload` from `backend/`). At every start the backend
**upgrades the existing database by itself** (new tables + new columns) and creates the default accounts.
`pip install -r requirements.txt` once (two new packages: PyJWT, python-dotenv).
Interactive docs: http://localhost:8000/docs  (click **Authorize**, paste the token from `/auth/login`).

## Default accounts (change the passwords before deploying)
| Role | Email | Password |
|---|---|---|
| admin | admin@supportpilot.dev | Admin@12345 |
| engineer (one per team) | network-team@ / identity-access-team@ / messaging-team@ / desktop-support-team@ / security-team@ / service-desk@ supportpilot.dev | Engineer@12345 |
| employee | register through `POST /auth/register` | your choice |

Settings (all optional, put them in the repo-root `.env`, never commit it): `AUTH_DISABLED`, `JWT_SECRET`,
`JWT_EXPIRE_MINUTES`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ENGINEER_PASSWORD`, `SEED_USERS`, `AUTO_RESOLVE_MIN_CONFIDENCE`.
`AUTH_DISABLED=true` makes every request act as an admin (development only - useful until the frontend login is ready).

## The journey of a ticket
```
create -> classify -> agents (or retrieval fallback) -> save AI answer -> DECIDE
   AI answer is good ........ status "Awaiting User"  (user is asked "Did this fix it?")
   needs a human ............ status "Escalated"      (team + SLA deadline + engineer assigned)
Awaiting User --feedback yes--> Resolved -> Closed          --feedback no--> Escalated
Escalated --accept--> In Progress --resolve--> Resolved --feedback yes--> Closed / --no--> In Progress (reopen)
```
A ticket goes to a human when ANY of these is true: classification failed / "Unknown", the AI answer is flagged
`needs_human_review`, its confidence is below `AUTO_RESOLVE_MIN_CONFIDENCE` (0.40), the agents say `escalate`,
the category is Security, the severity is Critical, or the AI side crashed. Nothing is ever lost or stuck.

Routing: category -> team (`config.ROUTING_RULES`), unknown -> Service Desk. SLA by priority:
P1 4h, P2 8h, P3 24h, P4 72h (`ticket.due_at`). The engineer of that team with the fewest open escalations is assigned.

Statuses: `Open, Classified, Awaiting User, Escalated, In Progress, Resolved, Closed`
(allowed moves are in `config.ALLOWED_TRANSITIONS`; anything else returns 400 with the allowed next statuses).

## Who can do what
| | employee | engineer | admin |
|---|---|---|---|
| create ticket | own (email taken from login) | for anyone | for anyone |
| see tickets | own | assigned to them or escalated to their team | all |
| feedback / reopen / "I want a human" | own tickets | - | yes |
| change status, escalation queue, notes, resolve | no | their team / assigned | all |
| users, assign, KB add/reindex, bulk CSV | no | no | yes |
| `/stats`, `/rag/stats`, agent runs | no | yes | yes |

A ticket you may not see returns **404** (existence is not revealed). Wrong role returns **403**. Missing/invalid/expired token returns **401**.

## Endpoints
**Auth** - `POST /auth/login {email,password}` and `POST /auth/register {name,email,password,department?}` both return
`{access_token, token_type, expires_in, user{user_id,name,email,department,role,team,...}}`.
Send `Authorization: Bearer <token>` on everything else. `GET /auth/me`, `POST /auth/change-password {old_password,new_password}`.

**Users (admin)** - `GET /users?role=&team=&q=&active=`, `POST /users {name,email,password,role,team?}` (an engineer needs a team),
`PATCH /users/{id} {name?,role?,team?,department?,is_active?,password?}` (you cannot demote/deactivate yourself),
`GET /teams` (staff: teams, routing rules, SLA hours).

**Tickets** - `POST /tickets {subject?,description,department?}`, `GET /tickets?status=&category=&priority=&severity=&assigned_to=&mine=&q=`,
`GET /tickets/{id}`, `/history`, `/response`, `POST /tickets/{id}/resolve` (regenerate the AI answer), `GET /tickets/{id}/agent-runs` (staff),
`PATCH /tickets/{id}/status {status}` (staff), `POST /tickets/{id}/reopen {reason?}`.
Ticket JSON now also has: `user_id, assigned_to, assignee_name, due_at, resolved_at, closed_at`.

**Feedback** - `POST /tickets/{id}/feedback {is_resolved, rating?(1-5), comment?}` only while the ticket is `Awaiting User` or `Resolved`;
`GET /tickets/{id}/feedback`.

**Escalation** - `POST /tickets/{id}/escalate {reason?}` (a person asks for a human), `GET /tickets/{id}/escalation`;
queue (staff): `GET /escalations?status=&team=&assigned_to=&unassigned=&mine=` (sorted by SLA deadline),
`GET /escalations/{id}`, `POST /escalations/{id}/accept`, `/notes {note, visible_to_user}`, `/resolve {notes}`, admin: `/assign {user_id}`.
Escalation JSON: `escalation_id, ticket_id, ticket_code, ticket_subject, ticket_category, ticket_severity, ticket_priority,
ticket_status, assigned_team, assigned_to, assignee_name, escalation_reason, escalated_by(AI/user/staff), status(Open/In Progress/Resolved),
due_at, resolution_notes, created_at, accepted_at, resolved_at`.

**Statistics (staff)** - `GET /stats` now also returns `escalations{total,open,unassigned,sla_breached,by_team}`,
`feedback{responses,fixed_issue,fixed_issue_pct,avg_rating,satisfaction_pct}` (satisfaction = share of ratings 4-5) and `integrations`.

Knowledge base: reading and searching is open to every logged-in user; `POST /kb/articles` and `POST /kb/reindex` are admin only.

## For Role B (agents) - `agents/orchestrator.py`
```python
run(ticket: dict) -> {
  "agent_trace": [{"agent": "Diagnosis", "status": "ok", "ms": 120, "confidence": 0.8, "summary": "..."}, ...],
  "diagnosis": {...}, "validation": {"passed": True, "confidence": 0.8, "notes": "..."},
  "resolution": {response_text, steps, sources, articles, confidence, mode, needs_human_review, trace, response_ms},  # same as rag.pipeline.resolve
  "decision": "auto_resolve" | "escalate", "escalate_to": "Network Team" | None, "reason": "why"}
```
`ticket` = ticket_id, ticket_code, subject, description, department, category, sub_category, severity, priority,
category_confidence, severity_confidence. **Do not write to the database**: the backend stores every `agent_trace` item in
`agent_runs` (agent_name, status, duration_ms, confidence, output) and the resolution in `ticket_responses`.
The final decision is still made by the backend (it also escalates Security, Critical and low-confidence answers), your `decision`
and `escalate_to` are taken into account. Until `agents/orchestrator.py` exists, the retrieval pipeline is used
(`GET /stats` -> `integrations.agents` shows `built-in-fallback` or `agents-package`).

## For Role C (Jira + email)
Both are called in a background thread after the database is committed; an error in them is printed and ignored.
```python
integrations/notifications.py:  notify(event, ticket_id, **context)
integrations/jira.py:           sync_ticket(db, ticket_id)      # db = a ready SQLAlchemy session
```
Events and their context: `ticket_received` (ticket_code, email), `ai_resolution_sent` (confidence), `escalated` (team, reason,
escalation_id, due_at), `assigned` (assignee_name, assignee_email, team), `status_changed` (old_status, new_status | message,
from_engineer), `resolved` (notes, resolved_by), `closed` (rating). Look up the ticket/user yourself with `ticket_id`.
Tables for you are already created: `jira_tickets`, `email_log`. `sync_ticket` is also called after every status change and assignment.

## For Roles D and E (frontend)
- Log in with `POST /auth/login`, keep `access_token` (and `user.role`) and send it as `Authorization: Bearer ...` from ONE api helper.
  On a 401 redirect to the login page. Show the user dashboard for `employee`, the staff dashboard for `engineer` and `admin`.
- An employee never sends `email` when creating a ticket. The "Did this fix it?" buttons call `/feedback` when status is `Awaiting User` or `Resolved`;
  "Talk to a human" calls `/escalate`.
- Queue screens: `GET /escalations` (already sorted by deadline); compare `due_at` with now for SLA warnings.

## Notes
- Old tickets created before login keep working: they belong to their (password-less) employee record, admins see them,
  and the employee can claim the account by registering with the same email.
- Seeded and dev accounts use the `@supportpilot.dev` domain (`.local` is rejected by email validation).
- 53 tests (`pytest` in `backend/`): they need no PostgreSQL, keys or internet.
