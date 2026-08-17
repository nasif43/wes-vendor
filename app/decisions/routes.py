from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile
from app.database import get_db
from app.decisions.models import Decision
from app.dependencies import get_current_user
from app.email.resend import build_decision_notification, send_batch
from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor
from app.vendors.models import Vendor

router = APIRouter()


@router.get("")
async def list_decisions(request: Request):
    return RedirectResponse(url="/past-orders", status_code=301)


@router.post("/new/{req_id}/{vendor_id}")
async def create_decision(
    req_id: str,
    vendor_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.auth.models import UserRole
    if not (user.is_procurement or user.is_management or user.role == UserRole.ADMIN):
        return RedirectResponse(url=f"/quotations/compare/{req_id}?error=Permission+denied", status_code=303)

    existing = await db.execute(
        select(Decision).where(Decision.requisition_id == req_id)
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(
            url=f"/quotations/compare/{req_id}?error=Decision+already+exists",
            status_code=303,
        )

    decision = Decision(
        requisition_id=req_id,
        winning_vendor_id=vendor_id,
        decided_by=user.id,
        management_approved=True,
        approved_by=user.id,
        approved_at=datetime.now(UTC),
    )
    db.add(decision)

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if req:
        from app.requisitions.service import transition_requisition_status
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=RequisitionStatus.SUBMITTED,
            actor=user,
            action_name="DECISION_CREATED_AND_APPROVED",
            notes=f"Winning vendor ID: {vendor_id}. Selected and approved by {user.full_name}",
        )

    # ── Send Vendor Selection Notification Email ───────────────────────────────
    email_params = []
    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.requisition_id == req_id)
    )
    vendor_links = result.scalars().all()

    for vl in vendor_links:
        vendor = vl.vendor
        if vendor and vendor.contact_email:
            is_winner = vl.vendor_id == vendor_id
            param = await build_decision_notification(
                to=vendor.contact_email,
                vendor_name=vendor.contact_person or vendor.company_name,
                requisition_title=req.title if req else "",
                approved=True if is_winner else False,
            )
            if param:
                email_params.append(param)

    if email_params:
        try:
            await send_batch(email_params)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to send vendor selection email: %s", e)

    return RedirectResponse(url=f"/quotations/compare/{req_id}?success=Vendor+selected+successfully", status_code=303)


@router.get("/{decision_id}", response_class=HTMLResponse)
async def view_decision(
    request: Request,
    decision_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        return RedirectResponse(url="/decisions", status_code=303)

    return templates.TemplateResponse(
        request, "decisions/detail.html", {"user": user, "decision": decision}
    )


@router.post("/{decision_id}/approve")
async def approve_decision(
    decision_id: str,
    approved: str = Form("true"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.auth.models import UserRole
    if user.role not in [UserRole.MANAGEMENT, UserRole.ADMIN] and not user.is_management:
        return RedirectResponse(url=f"/decisions/{decision_id}?error=Permission+denied", status_code=303)

    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        return RedirectResponse(url="/decisions?error=Decision+not+found", status_code=303)

    is_approved = approved == "true"
    decision.management_approved = is_approved
    decision.approved_by = user.id
    decision.approved_at = datetime.now(UTC)

    result = await db.execute(select(Requisition).where(Requisition.id == decision.requisition_id))
    req = result.scalar_one_or_none()
    if req:
        from app.requisitions.service import transition_requisition_status
        target_st = RequisitionStatus.SUBMITTED if is_approved else RequisitionStatus.IN_PROGRESS
        action_st = "DECISION_APPROVED" if is_approved else "DECISION_REJECTED"
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=target_st,
            actor=user,
            action_name=action_st,
            notes=f"Management Decision {'Approved' if is_approved else 'Rejected'} by {user.full_name}",
        )

    email_params = []
    # Send decision emails to vendors once management approves/rejects
    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.requisition_id == decision.requisition_id)
    )
    vendor_links = result.scalars().all()

    for vl in vendor_links:
        vendor = vl.vendor
        if vendor and vendor.contact_email:
            is_winner = vl.vendor_id == decision.winning_vendor_id
            param = await build_decision_notification(
                to=vendor.contact_email,
                vendor_name=vendor.contact_person or vendor.company_name,
                requisition_title=req.title if req else "",
                approved=is_approved and is_winner,
            )
            if param:
                email_params.append(param)

    if email_params:
        email_sent = await send_batch(email_params)
        if not email_sent:
            return RedirectResponse(
                url=f"/decisions/{decision_id}?warning=Decision+saved+but+vendor+notification+email+could+not+be+sent.",
                status_code=303,
            )

    return RedirectResponse(url=f"/decisions/{decision_id}?success=1", status_code=303)


