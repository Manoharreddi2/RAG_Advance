from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import ConversationDetail, ConversationOut
from app.db.models import Conversation, User
from app.db.session import get_db
from app.deps import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(limit: int = 50, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                            .order_by(Conversation.updated_at.desc()).limit(min(limit, 200)))
    return list(rows)


@router.get("/{conv_id}", response_model=ConversationDetail)
async def get_conversation(conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conv = await db.scalar(select(Conversation).options(selectinload(Conversation.messages))
                           .where(Conversation.id == conv_id, Conversation.user_id == user.id))
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.delete("/{conv_id}", status_code=204)
async def delete_conversation(conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    await db.delete(conv)
    await db.commit()
