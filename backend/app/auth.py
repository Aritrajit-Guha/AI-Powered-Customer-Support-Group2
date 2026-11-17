"""Who is calling? (login check + role check). Used as FastAPI dependencies."""
import re

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import config, security
from .database import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)  # gives the "Authorize" button in /docs (paste the token there)
DEV_ADMIN_EMAIL = "dev-admin@supportpilot.dev"


def _dev_admin(db: Session) -> User:
    """AUTH_DISABLED=true: act as an admin without logging in (development only)."""
    user = db.query(User).filter(User.email == DEV_ADMIN_EMAIL).first()
    if not user:
        user = User(name="Dev Admin", email=DEV_ADMIN_EMAIL, role="admin", department="IT", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    if config.AUTH_DISABLED:
        return _dev_admin(db)
    if not creds:
        raise HTTPException(401, "Not authenticated. Log in and send the token as 'Authorization: Bearer <token>'.",
                            headers={"WWW-Authenticate": "Bearer"})
    payload = security.decode_token(creds.credentials)
    if not payload:
        raise HTTPException(401, "Invalid or expired token. Please log in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, ValueError):
        user = None
    if not user or not user.is_active:
        raise HTTPException(401, "This account does not exist or has been deactivated.",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_roles(*roles: str):
    """Dependency factory: allow only the listed roles."""
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"This action needs one of these roles: {', '.join(roles)}.")
        return user
    return dependency


staff_only = require_roles("engineer", "admin")
admin_only = require_roles("admin")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def seed_default_users(db: Session) -> list:
    """Create the admin and one engineer per team if they do not exist yet. Returns what was created."""
    if not config.SEED_USERS:
        return []
    created = []
    wanted = [(config.ADMIN_EMAIL, "Admin", "admin", None, config.ADMIN_PASSWORD)]
    for team in config.TEAMS:
        wanted.append((f"{_slug(team)}@supportpilot.dev", f"{team} Engineer", "engineer", team,
                       config.ENGINEER_PASSWORD))
    for email, name, role, team, password in wanted:
        if db.query(User).filter(User.email == email).first():
            continue
        db.add(User(name=name, email=email, role=role, team=team, department="IT",
                    password_hash=security.hash_password(password), is_active=True))
        created.append(email)
    if created:
        db.commit()
    return created
