from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import RegisterIn, TokenOut, UserOut, UserUpdate
from app.config import get_settings
from app.core.rate_limit import rate_limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db
from app.deps import get_current_user, require_role

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(rate_limiter("auth"))])
users_router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    n_users = await db.scalar(select(func.count(User.id)))
    if not get_settings().allow_registration and n_users:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is disabled")
    email = body.email.lower()
    if await db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, hashed_password=hash_password(body.password), full_name=body.full_name,
                role="admin" if n_users == 0 else "viewer")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return TokenOut(access_token=create_access_token(str(user.id), user.role), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    return TokenOut(access_token=create_access_token(str(user.id), user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@users_router.get("", response_model=list[UserOut])
async def list_users(_: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(User).order_by(User.created_at))).all()


@users_router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdate, admin: User = Depends(require_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    import uuid
    user = await db.get(User, uuid.UUID(user_id))
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and (body.role and body.role != "admin" or body.is_active is False):
        raise HTTPException(400, "Admins cannot demote or disable themselves")
    if body.role:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    await db.commit()
    await db.refresh(user)
    return user
