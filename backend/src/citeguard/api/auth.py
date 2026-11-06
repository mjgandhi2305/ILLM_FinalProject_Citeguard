"""API-key authentication and per-key rate limiting."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from citeguard.api.state import AppState, get_state
from citeguard.db.repo import keys_equal


@dataclass(frozen=True)
class Principal:
    key_id: uuid.UUID | None
    is_admin: bool
    rate_limit_per_min: int

    @property
    def owner_filter(self) -> uuid.UUID | None:
        """None means "may see every check" (admin, or auth disabled)."""
        return None if self.is_admin else self.key_id

    @property
    def rate_key(self) -> str:
        return str(self.key_id) if self.key_id else "admin"


async def authenticate(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    st = get_state(request)
    if not st.settings.auth_enabled:
        return Principal(None, True, st.settings.default_rate_limit_per_min)
    raw = x_api_key
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
    if not raw:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    admin = st.settings.admin_api_key
    if admin is not None and keys_equal(raw, admin.get_secret_value()):
        return Principal(None, True, max(600, st.settings.default_rate_limit_per_min))
    row = await st.repo.find_api_key(raw)
    if row is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid API key", headers={"WWW-Authenticate": "Bearer"}
        )
    return Principal(row.id, False, row.rate_limit_per_min)


CurrentPrincipal = Annotated[Principal, Depends(authenticate)]


async def rate_limited(principal: CurrentPrincipal, request: Request) -> Principal:
    """Applied to endpoints that start (expensive) checks."""
    st: AppState = get_state(request)
    ok, retry_after = st.rate_limiter.allow(principal.rate_key, principal.rate_limit_per_min)
    if not ok:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Rate limit exceeded",
            headers={"Retry-After": str(max(1, int(retry_after + 0.5)))},
        )
    return principal


RateLimitedPrincipal = Annotated[Principal, Depends(rate_limited)]
