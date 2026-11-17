"""Calls into Role C's integrations (email + Jira), without ever blocking or breaking a request.

Contracts (agreed by the team):
    integrations.notifications.notify(event, ticket_id, **context)
        events: ticket_received, ai_resolution_sent, escalated, assigned, status_changed, resolved, closed
    integrations.jira.sync_ticket(db, ticket_id)

If those modules do not exist yet, nothing happens. Calls run in a background thread so that
ticket creation stays fast; an error inside them is printed and ignored.
"""
import importlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .database import SessionLocal

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

SYNC = False  # tests set this to True so the calls run immediately
session_factory = SessionLocal
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hooks")

EVENTS = ["ticket_received", "ai_resolution_sent", "escalated", "assigned", "status_changed", "resolved", "closed"]


def _load(modname: str):
    try:
        return importlib.import_module(modname)
    except ModuleNotFoundError as exc:
        if exc.name and modname.startswith(exc.name):  # the module itself is not in the repo yet
            return None
        print(f"[hooks] WARNING: {modname} found but a dependency is missing: {exc}")
        return None
    except Exception as exc:
        print(f"[hooks] WARNING: {modname} found but failed to load: {exc}")
        return None


_notifications = _load("integrations.notifications")
_jira = _load("integrations.jira")


def _run(job, label: str):
    def safe():
        try:
            job()
        except Exception as exc:  # never let an integration break the ticket flow
            print(f"[hooks] {label} failed: {exc}")

    if SYNC:
        safe()
    else:
        _pool.submit(safe)


def fire_notify(event: str, ticket_id: int, **context):
    if not hasattr(_notifications, "notify"):
        return
    _run(lambda: _notifications.notify(event, ticket_id, **context), f"notify({event})")


def fire_jira_sync(ticket_id: int):
    if not hasattr(_jira, "sync_ticket"):
        return

    def job():
        with session_factory() as db:
            _jira.sync_ticket(db, ticket_id)

    _run(job, "jira sync")


def status() -> dict:
    return {
        "notifications": "integrations-package" if hasattr(_notifications, "notify") else "not-installed",
        "jira": "integrations-package" if hasattr(_jira, "sync_ticket") else "not-installed",
    }
