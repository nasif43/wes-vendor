from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.auth.models import UserProfile, UserRole
from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter()

ALLOWED_ROLES = {UserRole.MANAGEMENT, UserRole.ADMIN}


@router.get("", response_class=HTMLResponse)
async def list_audit_logs(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    if user.role not in ALLOWED_ROLES:
        return RedirectResponse(url="/", status_code=303)

    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)
    )
    logs = result.scalars().all()

    return templates.TemplateResponse(
        request, "audit/list.html", {"user": user, "logs": logs}
    )
