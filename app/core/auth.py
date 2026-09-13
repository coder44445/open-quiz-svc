"""Quiz-service auth dependency.

Verifies JWTs signed with HS256 by the Identity service.
Two entrypoints are provided:

* ``require_auth``   — HTTP FastAPI dependency (reads ``Authorization: Bearer``).
* ``ws_auth``        — Async helper for WebSocket handshakes (reads ``?token=``
                       query parameter, since browsers cannot send custom headers
                       when opening a WebSocket connection).

Both respect ``PLATFORM_AUTH_ENABLED``.  When it is False the caller is allowed
through so existing unauthenticated dev/test flows keep working.  Set it to True
(and add the correct ``JWT_SECRET`` to ``.env``) to enforce authentication.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import logger

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    """Authenticated caller identity."""

    user_id: uuid.UUID
    roles: list[str] = field(default_factory=list)

    def is_admin(self) -> bool:
        return "platform_admin" in self.roles


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_token(token: str) -> AuthUser:
    """Decode and verify an HS256 JWT.  Raises HTTPException on any failure."""
    try:
        from jose import JWTError, jwt  # deferred so tests can mock it easily

        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except Exception as exc:  # JWTError or import error
        logger.warning("quiz_jwt_verification_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    try:
        user_id = uuid.UUID(str(payload.get("sub", "")))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sub claim is not a valid UUID",
        )

    roles: list[str] = payload.get("roles", []) or []
    return AuthUser(user_id=user_id, roles=roles)


# ---------------------------------------------------------------------------
# HTTP dependency (REST endpoints)
# ---------------------------------------------------------------------------

async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser | None:
    """FastAPI dependency — returns ``AuthUser`` or ``None`` when auth is off.

    Raise 401 if auth is enabled but the token is absent or invalid.
    """
    if not settings.platform_auth_enabled:
        return None  # Auth is disabled — allow through

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with Bearer token is required",
        )

    return _decode_token(credentials.credentials)


# ---------------------------------------------------------------------------
# WebSocket helper
# ---------------------------------------------------------------------------

async def ws_auth(websocket: WebSocket) -> AuthUser | None:
    """Extract and verify the JWT from the ``?token=`` WebSocket query param.

    Returns ``None`` when ``PLATFORM_AUTH_ENABLED=false``.
    Closes the WebSocket with a 4001 code and returns ``None`` on failure so
    the router can exit cleanly without raising inside the WS context.
    """
    if not settings.platform_auth_enabled:
        return None

    token: str | None = websocket.query_params.get("token")
    if not token:
        logger.warning("ws_auth_missing_token")
        await websocket.close(code=4001, reason="Authentication required")
        return None

    try:
        return _decode_token(token)
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return None
