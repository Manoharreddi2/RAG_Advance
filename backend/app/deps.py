from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token, has_role
from app.db.models import User
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(request: Request, token: str | None = Depends(oauth2_scheme),
                           db: AsyncSession = Depends(get_db)) -> User:
    # EventSource cannot set headers, so SSE/file preview may pass ?access_token=
    token = token or request.query_params.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token", headers={"WWW-Authenticate": "Bearer"})
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    request.state.user_id = user.id
    return user


def require_role(role: str):
    async def dep(user: User = Depends(get_current_user)) -> User:
        if not has_role(user.role, role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{role}'")
        return user
    return dep
