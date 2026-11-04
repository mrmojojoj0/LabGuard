import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from labguard_server.config import Settings
from labguard_server.db import get_db
from labguard_server.models import AdminSession, Administrator, now_utc

password_hasher = PasswordHasher()
ROLE_LEVEL = {"VIEWER": 0, "OPERATOR": 1, "LAB_ADMIN": 2, "SUPER_ADMIN": 3}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def current_admin(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("labguard_session")
    if not token:
        raise HTTPException(status_code=401, detail={"code": "authentication_required", "message": "Authentication required"})
    session_row = db.scalar(select(AdminSession).where(AdminSession.token_hash == digest(token)))
    now = now_utc()
    if session_row is None or session_row.revoked_at is not None or session_row.expires_at.replace(tzinfo=now.tzinfo) <= now:
        raise HTTPException(status_code=401, detail={"code": "invalid_session", "message": "Session expired or revoked"})
    admin = db.get(Administrator, session_row.administrator_id)
    if admin is None or not admin.enabled:
        raise HTTPException(status_code=401, detail={"code": "invalid_session", "message": "Session is unavailable"})
    session_row.last_used_at = now
    return admin, session_row


def csrf_protected(request: Request, auth=Depends(current_admin)):
    _, session_row = auth
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(digest(supplied), session_row.csrf_hash):
        raise HTTPException(status_code=403, detail={"code": "csrf_failed", "message": "Valid CSRF token required"})
    return auth


def require_role(minimum: str, csrf: bool = False):
    dependency = csrf_protected if csrf else current_admin

    def check(auth=Depends(dependency)):
        admin, _session = auth
        if ROLE_LEVEL.get(admin.role, -1) < ROLE_LEVEL[minimum]:
            raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Insufficient role"})
        return admin

    return check


def create_admin_session(db: Session, admin: Administrator, settings: Settings):
    raw_token, csrf = new_secret(), new_secret()
    row = AdminSession(
        administrator_id=admin.id,
        token_hash=digest(raw_token),
        csrf_hash=digest(csrf),
        expires_at=now_utc() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(row)
    return raw_token, csrf, row
