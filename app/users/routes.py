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


@router.post("/new")
async def create_user(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    role: str = Form("procurement"),
    can_view_quotations: bool = Form(False),
    can_do_qc: bool = Form(False),
    can_view_all_requisitions: bool = Form(False),
    is_management: bool = Form(False),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    if not user.has_management_authority and user.role != UserRole.ADMIN:
        return RedirectResponse(url="/users?error=Permission+denied", status_code=303)

    clean_email = email.strip().lower()
    clean_name = full_name.strip()

    if not clean_email or not clean_name:
        return RedirectResponse(url="/users?error=Name+and+Email+are+required", status_code=303)

    result = await db.execute(
        select(UserProfile).where(func.lower(UserProfile.email) == clean_email)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return RedirectResponse(url="/users?error=Email+already+registered", status_code=303)

    # Resolve role enum
    target_role = UserRole.PROCUREMENT
    for r in UserRole:
        if r.value == role or r.name.lower() == role.lower():
            target_role = r
            break

    # If role is management or admin, automatically set management flags
    final_is_mgmt = is_management or target_role in (UserRole.MANAGEMENT, UserRole.ADMIN)
    final_view_quotes = can_view_quotations or final_is_mgmt
    final_view_all = can_view_all_requisitions or final_is_mgmt or target_role == UserRole.QC_RECEIVER
    final_do_qc = can_do_qc or final_is_mgmt or target_role == UserRole.QC_RECEIVER

    new_user = UserProfile(
        email=clean_email,
        full_name=clean_name,
        role=target_role,
        can_view_quotations=final_view_quotes,
        can_do_qc=final_do_qc,
        can_view_all_requisitions=final_view_all,
        is_management=final_is_mgmt,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    await log_action(
        db,
        actor=user,
        action="USER_PROVISIONED",
        entity_type="user_profile",
        entity_id=new_user.id,
        entity_label=new_user.full_name,
        notes=f"User account created by {user.full_name} ({user.email}). Role: {target_role.value}.",
    )

    await db.flush()
    return RedirectResponse(
        url=f"/users?success=User+{new_user.full_name.replace(' ', '+')}+created+successfully",
        status_code=303,
    )


@router.post("/{target_user_id}/permissions")
async def update_user_permissions(
    target_user_id: str,
    request: Request,
    role: str = Form(None),
    can_view_quotations: bool = Form(False),
    can_do_qc: bool = Form(False),
    can_view_all_requisitions: bool = Form(False),
    is_management: bool = Form(False),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.has_management_authority:
        return RedirectResponse(url="/?error=Permission+denied", status_code=303)

    result = await db.execute(select(UserProfile).where(UserProfile.id == target_user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        return RedirectResponse(url="/users?error=User+not+found", status_code=303)

    old_role = str(target_user.role.value if hasattr(target_user.role, "value") else target_user.role)
    old_view_quotes = target_user.can_view_quotations
    old_do_qc = target_user.can_do_qc
    old_view_all = target_user.can_view_all_requisitions
    old_is_mgmt = target_user.is_management

    target_user.can_view_quotations = can_view_quotations
    target_user.can_do_qc = can_do_qc
    target_user.can_view_all_requisitions = can_view_all_requisitions
    target_user.is_management = is_management

    if role:
        for r in UserRole:
            if r.value == role or r.name.lower() == role.lower():
                target_user.role = r
                break

    # ── Audit log ──────────────────────────────────────────────────────────────
    changes = []
    if role and old_role != str(target_user.role.value if hasattr(target_user.role, "value") else target_user.role):
        changes.append(f"Role: {target_user.role.value}")
    if old_view_quotes != can_view_quotations:
        changes.append(f"Quotation Visibility: {'Granted' if can_view_quotations else 'Revoked'}")
    if old_do_qc != can_do_qc:
        changes.append(f"QC Receiver Rights: {'Granted' if can_do_qc else 'Revoked'}")
    if old_view_all != can_view_all_requisitions:
        changes.append(f"All Requisitions Visibility: {'Granted' if can_view_all_requisitions else 'Revoked'}")
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


@router.post("/{target_user_id}/toggle-active")
async def toggle_user_active(
    target_user_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.has_management_authority and user.role != UserRole.ADMIN:
        return RedirectResponse(url="/users?error=Permission+denied", status_code=303)

    if user.id == target_user_id:
        return RedirectResponse(url="/users?error=You+cannot+deactivate+your+own+account", status_code=303)

    result = await db.execute(select(UserProfile).where(UserProfile.id == target_user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        return RedirectResponse(url="/users?error=User+not+found", status_code=303)

    target_user.is_active = not target_user.is_active
    status_label = "Activated" if target_user.is_active else "Deactivated"

    await log_action(
        db,
        actor=user,
        action="USER_STATUS_TOGGLED",
        entity_type="user_profile",
        entity_id=target_user.id,
        entity_label=target_user.full_name,
        notes=f"User {target_user.full_name} ({target_user.email}) marked as {status_label} by {user.full_name}.",
    )

    await db.flush()
    return RedirectResponse(
        url=f"/users?success=User+{target_user.full_name.replace(' ', '+')}+{status_label.lower()}",
        status_code=303,
    )


@router.post("/{target_user_id}/delete")
async def delete_user(
    target_user_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.has_management_authority and user.role != UserRole.ADMIN:
        return RedirectResponse(url="/users?error=Permission+denied", status_code=303)

    if user.id == target_user_id:
        return RedirectResponse(url="/users?error=You+cannot+delete+your+own+account", status_code=303)

    result = await db.execute(select(UserProfile).where(UserProfile.id == target_user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        return RedirectResponse(url="/users?error=User+not+found", status_code=303)

    user_name = target_user.full_name
    user_email = target_user.email

    try:
        await db.delete(target_user)
        await db.flush()
        await log_action(
            db,
            actor=user,
            action="USER_DELETED",
            entity_type="user_profile",
            entity_id=target_user_id,
            entity_label=user_name,
            notes=f"User {user_name} ({user_email}) permanently removed by {user.full_name}.",
        )
        return RedirectResponse(url=f"/users?success=User+{user_name.replace(' ', '+')}+deleted", status_code=303)
    except Exception:
        await db.rollback()
        # Fallback to safe deactivation if foreign key constraints exist (e.g. user created requisitions or performed QC)
        result = await db.execute(select(UserProfile).where(UserProfile.id == target_user_id))
        target_user = result.scalar_one_or_none()
        if target_user:
            target_user.is_active = False
            await log_action(
                db,
                actor=user,
                action="USER_DEACTIVATED_SAFE",
                entity_type="user_profile",
                entity_id=target_user.id,
                entity_label=user_name,
                notes=f"User {user_name} has linked history (requisitions/QC); account safely deactivated instead of deleted to protect audit logs.",
            )
            await db.flush()
        return RedirectResponse(
            url=f"/users?warning=User+{user_name.replace(' ', '+')}+has+linked+order+history.+Account+was+deactivated+to+preserve+audit+trail.",
            status_code=303,
        )
