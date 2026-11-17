"""Settings.

Everything has a safe default, so the backend runs without a .env file.
If a .env exists in the repo root (the same file Roles B and C use for
Gemini / Pinecone / SMTP / Jira keys) it is loaded automatically.
NEVER commit .env or real passwords.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

try:  # optional: python-dotenv
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://supportpilot:supportpilot@localhost:5432/supportpilot",
)

# Allowed values, agreed by the whole team. Do not change without telling everyone.
CATEGORIES = ["Network", "VPN", "Software", "Hardware", "Password Reset", "Email", "Security"]
SEVERITIES = ["Low", "Medium", "High", "Critical"]
PRIORITIES = ["P1", "P2", "P3", "P4"]

# ------------------------------------------------------------------ Milestone 3: login and roles
# AUTH_DISABLED=true  ->  every request is treated as an admin (local development only!)
AUTH_DISABLED = _flag("AUTH_DISABLED", False)
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-secret-change-me-before-deploying")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

ROLES = ["employee", "engineer", "admin"]
STAFF_ROLES = ("engineer", "admin")

# Accounts created automatically on first start (change the passwords before deploying!)
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@supportpilot.dev")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@12345")
ENGINEER_PASSWORD = os.environ.get("ENGINEER_PASSWORD", "Engineer@12345")
SEED_USERS = _flag("SEED_USERS", True)

# ------------------------------------------------------------------ routing, SLA and escalation policy
TEAMS = [
    "Network Team",
    "Identity & Access Team",
    "Messaging Team",
    "Desktop Support Team",
    "Security Team",
    "Service Desk",
]
DEFAULT_TEAM = "Service Desk"
ROUTING_RULES = {  # category -> team
    "Network": "Network Team",
    "VPN": "Network Team",
    "Password Reset": "Identity & Access Team",
    "Email": "Messaging Team",
    "Hardware": "Desktop Support Team",
    "Software": "Desktop Support Team",
    "Security": "Security Team",
}
SLA_HOURS = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}  # priority -> hours to resolve

# These always go to a human, even when the AI answer looks confident.
ESCALATE_CATEGORIES = ["Security"]
ESCALATE_SEVERITIES = ["Critical"]
# Extra safety net on top of the AI's own needs_human_review flag.
AUTO_RESOLVE_MIN_CONFIDENCE = float(os.environ.get("AUTO_RESOLVE_MIN_CONFIDENCE", "0.40"))

# ------------------------------------------------------------------ ticket lifecycle
# current status -> statuses it is allowed to move to
#   Open -> Classified -> Awaiting User (AI answer sent) -> Resolved -> Closed
#   Classified/Awaiting User/In Progress -> Escalated -> In Progress -> Resolved -> Closed
ALLOWED_TRANSITIONS = {
    "Open": ["Classified", "Escalated"],
    "Classified": ["Awaiting User", "Escalated", "In Progress"],
    "Awaiting User": ["Resolved", "Escalated"],
    "Escalated": ["In Progress"],
    "In Progress": ["Resolved", "Escalated"],
    "Resolved": ["Closed", "In Progress"],  # In Progress = reopened
    "Closed": [],
}
ESCALATION_STATUSES = ["Open", "In Progress", "Resolved"]

# --- Milestone 2: knowledge base (the files are the source of truth) ---
KB_DIR = REPO_ROOT / "data" / "kb"  # data/kb/<category>/<slug>.md
RETRIEVAL_METRICS_FILE = REPO_ROOT / "data" / "retrieval_metrics.json"  # written by Role B's eval script
