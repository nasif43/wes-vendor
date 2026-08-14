from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserProfile
from app.database import get_db


async def _get_user_id(request: Request) -> str | None:
    return request.session.get("user_id")


async def get_current_user(
    request: Request,
    user_id: str | None = Depends(_get_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/login"},
        )
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/auth/login"},
        )
    return user


def require_role(*roles: str):
    async def checker(
        user: Annotated[UserProfile, Depends(get_current_user)],
    ) -> UserProfile:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user
    return checker


CurrentUser = Annotated[UserProfile, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
