"""
Replaces the MVP shared-key stub entirely. Every protected route now knows WHICH user
made the request (not just "someone with the key"), and roles are enforced per-route.

Roles: admin (user management + everything), reviewer (extraction, checks, approvals),
viewer (read-only: audit log, flags). Matches the doc's real-world personas: an officer
reviewing flags is a "reviewer", a citizen-facing dashboard viewer is "viewer", and
whoever owns the deployment is "admin".
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.security import decode_access_token, TokenError

ROLE_HIERARCHY = {"viewer": 0, "reviewer": 1, "admin": 2}

# Using FastAPI's HTTPBearer class (not a raw Header(str)) is what registers a proper
# securityScheme in the OpenAPI spec — this is the actual difference that makes Swagger
# UI render the lock icons and the global "Authorize" button, instead of exposing
# "authorization" as a plain manual text field on every single protected route.
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {e}")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return user


def require_role(minimum_role: str):
    """Dependency factory: Depends(require_role('reviewer')) allows reviewer AND admin,
    since admin sits above reviewer in ROLE_HIERARCHY."""
    def _check(user: User = Depends(get_current_user)) -> User:
        if ROLE_HIERARCHY.get(user.role, -1) < ROLE_HIERARCHY.get(minimum_role, 999):
            raise HTTPException(
                status_code=403,
                detail=f"Requires role '{minimum_role}' or higher, you have '{user.role}'",
            )
        return user
    return _check
