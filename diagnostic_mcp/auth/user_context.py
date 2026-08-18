"""Identity 2: the calling user, resolved independently of the service token.

Every tool call carries a user-context token. The server resolves this
user's factory grants and rejects the call before the service token is
used for anything (BRIDGE-2) - see diagnostic_mcp/registry/pipeline.py.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt

from diagnostic_mcp.auth.errors import AuthenticationError


@dataclass(frozen=True)
class UserIdentity:
    user_id: str
    org_id: str


def issue_user_context_token(
    secret: str, user_id: str, org_id: str, *, ttl_seconds: int = 3600
) -> str:
    """Mint a user-context token. Test/dev use only - in production this is
    issued by Pulse's own auth and carried through on every call."""
    now = int(time.time())
    payload = {"sub": user_id, "org_id": org_id, "iat": now, "exp": now + ttl_seconds}
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_user_context_token(token: str, secret: str) -> UserIdentity:
    """Verify signature and expiry. Fails closed: no fallback identity."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthenticationError(f"Invalid user-context token: {exc}") from exc

    user_id = payload.get("sub")
    org_id = payload.get("org_id")
    if not user_id or not org_id:
        raise AuthenticationError("User-context token missing sub/org_id.")

    return UserIdentity(user_id=user_id, org_id=org_id)
