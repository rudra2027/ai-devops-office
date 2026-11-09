"""
Supabase authentication. The browser signs in with Supabase and sends the access token as `Authorization: Bearer`.
We validate it by asking Supabase (works for both legacy and asymmetric signing keys), cache the answer briefly, and
forward the same token to PostgREST so row level security applies to every query.
"""

import hashlib
import json
import uuid
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .cache import get_cache
from .settings import admin_set, get_settings

_bearer = HTTPBearer(auto_error=False)
_client: Optional[httpx.AsyncClient] = None


class AuthUser(BaseModel):
    id: str
    email: Optional[str] = None
    token: str = ""
    is_admin: bool = False


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10)
    return _client


async def verify_token(token: str) -> AuthUser:
    s = get_settings()
    if s.auth_mode == "dev":
        # Local tests only. Never enable in a deployed environment.
        if token.startswith("dev:"):
            email = token[4:].strip() or "dev@example.com"
            return AuthUser(id=str(uuid.uuid5(uuid.NAMESPACE_DNS, email)), email=email, token=token, is_admin=email.lower() in admin_set(s))
        raise HTTPException(401, "Invalid dev token")

    if not s.supabase_url or not s.supabase_publishable_key:
        raise HTTPException(503, "Supabase is not configured")
    ck = "auth:" + hashlib.sha256(token.encode()).hexdigest()
    cache = get_cache()
    hit = cache.get(ck)
    if hit:
        d = json.loads(hit)
        return AuthUser(id=d["id"], email=d.get("email"), token=token, is_admin=bool(d.get("admin")))
    try:
        r = await _http().get(
            f"{s.supabase_url}/auth/v1/user",
            headers={"apikey": s.supabase_publishable_key, "Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError:
        raise HTTPException(503, "Authentication service unreachable")
    if r.status_code != 200:
        raise HTTPException(401, "Invalid or expired session")
    u = r.json()
    # Admin only if the address is on the list AND Supabase says the owner confirmed it, so nobody can sign up as the admin.
    admin = bool(u.get("email")) and u["email"].lower() in admin_set(s) and bool(u.get("email_confirmed_at") or u.get("confirmed_at"))
    cache.set(ck, json.dumps({"id": u["id"], "email": u.get("email"), "admin": admin}), ttl=60)
    return AuthUser(id=u["id"], email=u.get("email"), token=token, is_admin=admin)


async def require_user(cred: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> AuthUser:
    if cred is None or not cred.credentials:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    return await verify_token(cred.credentials)


async def require_admin(user: AuthUser = Depends(require_user)) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    return user


async def admin_from_request(request: Request) -> AuthUser:
    """For server-sent events: EventSource cannot set headers, so the token may come as ?access_token=."""
    token = request.query_params.get("access_token")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        raise HTTPException(401, "Sign in required")
    user = await verify_token(token)
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    return user
