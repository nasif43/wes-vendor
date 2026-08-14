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


@router.get("", response_class=HTMLResponse)
async def list_decisions(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Decision).order_by(Decision.decided_at.desc()))
    decisions = result.scalars().all()
    return templates.TemplateResponse(
        request, "decisions/list.html", {"user": user, "decisions": decisions}
    )


@router.post("/new/{req_id}/{vendor_id}")
async def create_decision(
    req_id: str,
    vendor_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.auth.models import UserRole
    if user.role not in [UserRole.PURCHASE_PERSON, UserRole.ADMIN]:
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
    )
    db.add(decision)

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if req:
        req.status = RequisitionStatus.IN_PROGRESS

    # ── Audit log ──────────────────────────────────────────────────────────────
    await log_action(
        db,
        actor=user,
        action="DECISION_CREATED",
        entity_type="decision",
        entity_id=decision.id,
        entity_label=req.title if req else req_id,
        notes=f"Winning vendor ID: {vendor_id}",
    )

    return RedirectResponse(url="/decisions?success=1", status_code=303)


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
    if user.role not in [UserRole.MANAGEMENT, UserRole.ADMIN]:
        return RedirectResponse(url=f"/decisions/{decision_id}?error=Permission+denied", status_code=303)

    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    email_params = []
    if decision:
        is_approved = approved == "true"
        decision.management_approved = is_approved
        decision.approved_by = user.id
        decision.approved_at = datetime.now(UTC)
        await db.flush()

        result = await db.execute(select(Requisition).where(Requisition.id == decision.requisition_id))
        req = result.scalar_one_or_none()
        if req and is_approved:
            req.status = RequisitionStatus.SUBMITTED

        # ── Audit log ──────────────────────────────────────────────────────────
        _req_title = decision.requisition.title if decision.requisition else decision.requisition_id
        await log_action(
            db,
            actor=user,
            action="DECISION_APPROVED" if is_approved else "DECISION_REJECTED",
            entity_type="decision",
            entity_id=decision.id,
            entity_label=_req_title,
            notes=f"Approved by {user.full_name} ({user.email})"
                  if is_approved
                  else f"Rejected by {user.full_name} ({user.email})",
        )

        result = await db.execute(select(Requisition).where(Requisition.id == decision.requisition_id))
        req = result.scalar_one_or_none()

        result = await db.execute(
            select(RequisitionVendor).where(RequisitionVendor.requisition_id == decision.requisition_id)
        )
        vendor_links = result.scalars().all()

        for vl in vendor_links:
            result = await db.execute(select(Vendor).where(Vendor.id == vl.vendor_id))
            vendor = result.scalar_one_or_none()
            if vendor and vendor.contact_email:
                is_winner = vl.vendor_id == decision.winning_vendor_id
                param = build_decision_notification(
                    to=vendor.contact_email,
                    vendor_name=vendor.contact_person or vendor.company_name,
                    requisition_title=req.title if req else "",
                    approved=is_approved and is_winner,
                )
                if param:
                    email_params.append(param)

    if not email_params:
        return RedirectResponse(url=f"/decisions/{decision_id}?success=1", status_code=303)
    email_sent = await send_batch(email_params)
    if not email_sent:
        return RedirectResponse(
            url=f"/decisions/{decision_id}?error=Decision+saved+but+email+notification+failed.",
            status_code=303,
        )
    return RedirectResponse(url=f"/decisions/{decision_id}?success=1", status_code=303)
