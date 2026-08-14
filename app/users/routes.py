from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile, UserRole
from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    if not user.has_management_authority:
        return RedirectResponse(url="/?error=Permission+denied", status_code=303)

    result = await db.execute(select(UserProfile).order_by(UserProfile.full_name))
    users_list = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "users/list.html",
        {"user": user, "users_list": users_list},
    )


@router.post("/{target_user_id}/permissions")
async def update_user_permissions(
    target_user_id: str,
    request: Request,
    can_view_quotations: bool = Form(False),
    can_do_qc: bool = Form(False),
    is_management: bool = Form(False),
    role: str = Form("requester"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.has_management_authority:
        return RedirectResponse(url="/?error=Permission+denied", status_code=303)

    result = await db.execute(select(UserProfile).where(UserProfile.id == target_user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        return RedirectResponse(url="/users?error=User+not+found", status_code=303)

    old_view_quotes = target_user.can_view_quotations
    old_do_qc = target_user.can_do_qc
    old_is_mgmt = target_user.is_management

    target_user.can_view_quotations = can_view_quotations
    target_user.can_do_qc = can_do_qc
    target_user.is_management = is_management
    
    if role in [r.value for r in UserRole]:
        target_user.role = UserRole(role)

    # ── Audit log ──────────────────────────────────────────────────────────────
    changes = []
    if old_view_quotes != can_view_quotations:
        changes.append(f"Quotation Visibility: {'Granted' if can_view_quotations else 'Revoked'}")
    if old_do_qc != can_do_qc:
        changes.append(f"QC Receiver Rights: {'Granted' if can_do_qc else 'Revoked'}")
    if old_is_mgmt != is_management:
        changes.append(f"Management Authority: {'Granted' if is_management else 'Revoked'}")

    change_summary = ", ".join(changes) if changes else "Permissions updated"

    await log_action(
        db,
        actor=user,
        action="USER_PERMISSIONS_UPDATED",
        entity_type="user_profile",
        entity_id=target_user.id,
        entity_label=target_user.full_name,
        notes=f"Updated permissions for {target_user.full_name} ({target_user.email}): {change_summary} by {user.full_name} ({user.email}).",
    )

    await db.flush()
    return RedirectResponse(
        url=f"/users?success=Permissions+updated+for+{target_user.full_name.replace(' ', '+')}",
        status_code=303,
    )
