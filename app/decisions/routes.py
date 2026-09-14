"""
Decisions routes — legacy compatibility layer.

NEW FLOW: Winners are selected by management on the compare page,
which creates WorkOrder records (see app/work_orders/routes.py).

This module is kept for backward compatibility with existing Decision records
and to handle the management approval flow.
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile, UserRole
from app.database import get_db
from app.decisions.models import Decision
from app.dependencies import get_current_user
from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor
from app.vendors.models import Vendor

logger = logging.getLogger(__name__)
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
    """Select a winner for a requisition.
    
    Management-only. Creates a Decision record for legacy compat and
    transitions requisition to AWARDED. The actual WorkOrder is issued
    separately by Procurement via POST /work-orders/issue/{req_id}/{rv_id}.
    """
    if not (user.is_management or user.role == UserRole.ADMIN):
        return RedirectResponse(
            url=f"/quotations/compare/{req_id}?error=Only+management+can+select+winners",
            status_code=303,
        )

    # Check if decision already exists
    existing = await db.execute(
        select(Decision).where(Decision.requisition_id == req_id)
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(
            url=f"/quotations/compare/{req_id}?error=Winner+already+selected",
            status_code=303,
        )

    decision = Decision(
        requisition_id=req_id,
        winning_vendor_id=vendor_id,
        decided_by=user.id,
        management_approved=True,
        approved_by=user.id,
        approved_at=datetime.now(UTC),
        work_order_status="pending_issuance",
    )
    db.add(decision)

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if req:
        from app.requisitions.service import transition_requisition_status
        # Transition to AWARDED — procurement can now issue work order
        current = req.status
        if isinstance(current, str):
            current = RequisitionStatus(current)
        
        # Allow transitioning from IN_PROGRESS or NEGOTIATING to AWARDED
        target = RequisitionStatus.AWARDED
        try:
            await transition_requisition_status(
                db,
                requisition=req,
                target_status=target,
                actor=user,
                action_name="WINNER_SELECTED",
                notes=f"Winner: vendor_id={vendor_id}. Selected by {user.full_name}. Awaiting work order issuance by Procurement.",
            )
        except Exception as e:
            logger.warning("Could not transition to AWARDED (current=%s): %s", current, e)
            # Fall back — try SUBMITTED for legacy compat
            try:
                await transition_requisition_status(
                    db,
                    requisition=req,
                    target_status=RequisitionStatus.SUBMITTED,
                    actor=user,
                    action_name="WINNER_SELECTED",
                    notes=f"Winner: vendor_id={vendor_id}. Selected by {user.full_name}.",
                )
            except Exception:
                pass

    # Send decision notification emails to all vendors
    try:
        from app.email.resend import build_decision_notification, send_batch
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
            await send_batch(email_params)
    except Exception:
        logger.exception("Failed to send winner notification emails for req %s", req_id)

    await db.commit()
    return RedirectResponse(
        url=f"/quotations/compare/{req_id}?success=Winner+selected.+Procurement+can+now+issue+work+order.",
        status_code=303,
    )


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
    """Legacy management approval flow. In new flow, selection IS approval.
    
    Kept for backward compat with existing Decision records that have
    management_approved=None (pending approval).
    """
    if user.role not in [UserRole.MANAGEMENT, UserRole.ADMIN] and not user.is_management:
        return RedirectResponse(
            url=f"/decisions/{decision_id}?error=Permission+denied",
            status_code=303,
        )

    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        return RedirectResponse(url="/decisions?error=Decision+not+found", status_code=303)

    is_approved = approved == "true"
    decision.management_approved = is_approved
    decision.approved_by = user.id
    decision.approved_at = datetime.now(UTC)

    result = await db.execute(
        select(Requisition).where(Requisition.id == decision.requisition_id)
    )
    req = result.scalar_one_or_none()
    if req:
        from app.requisitions.service import transition_requisition_status, InvalidStateTransitionError
        if is_approved:
            target_st = RequisitionStatus.AWARDED
            action_st = "DECISION_APPROVED"
        else:
            target_st = RequisitionStatus.IN_PROGRESS
            action_st = "DECISION_REJECTED"
        try:
            await transition_requisition_status(
                db,
                requisition=req,
                target_status=target_st,
                actor=user,
                action_name=action_st,
                notes=f"Management {'Approved' if is_approved else 'Rejected'} by {user.full_name}",
            )
        except InvalidStateTransitionError as e:
            logger.warning("State transition failed on approve: %s", e)

    # Send vendor notification emails
    try:
        from app.email.resend import build_decision_notification, send_batch
        email_params = []
        result = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.requisition_id == decision.requisition_id
            )
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
            await send_batch(email_params)
    except Exception:
        logger.exception("Failed to send approval notification emails")

    await db.commit()
    return RedirectResponse(
        url=f"/decisions/{decision_id}?success=Decision+{'approved' if is_approved else 'rejected'}",
        status_code=303,
    )


@router.post("/{decision_id}/approve_work_order")
async def approve_work_order(
    decision_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy endpoint — kept for backward compat.
    
    In new flow, work orders are issued via POST /work-orders/issue/{req_id}/{rv_id}.
    This endpoint now just sets the legacy work_order_status flag and redirects.
    """
    if user.role not in [UserRole.MANAGEMENT, UserRole.ADMIN] and not user.is_management:
        return RedirectResponse(
            url=f"/decisions/{decision_id}?error=Permission+denied",
            status_code=303,
        )

    result = await db.execute(select(Decision).where(Decision.id == decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        return RedirectResponse(url="/decisions?error=Decision+not+found", status_code=303)

    decision.work_order_status = "approved"

    # Attempt PDF generation and email using new service
    try:
        from app.work_orders.service import generate_work_order_pdf, send_work_order_email
        from app.work_orders.models import WorkOrder
        from app.settings.models import SystemSettings
        import uuid

        active_slot_row = await db.get(SystemSettings, "active_letterhead")
        letterhead_url = None
        if active_slot_row:
            lh_row = await db.get(SystemSettings, f"letterhead_{active_slot_row.value}")
            if lh_row:
                letterhead_url = lh_row.value

        # Get winning vendor link for PDF data
        from app.requisitions.models import RequisitionVendor
        wv_res = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.requisition_id == decision.requisition_id,
                RequisitionVendor.vendor_id == decision.winning_vendor_id,
            ).order_by(RequisitionVendor.created_at.desc())
        )
        winning_link = wv_res.scalars().first()

        # Build a transient WorkOrder-like object for PDF generation
        class _WOProxy:
            id = decision.id
            issued_at = decision.approved_at or datetime.now(UTC)
            requisition = decision.requisition
            vendor = decision.winning_vendor
            issuer = decision.approver
            _quotation_data = (
                winning_link.quotation.form_data
                if winning_link and winning_link.quotation
                else None
            )

        pdf_bytes = await generate_work_order_pdf(_WOProxy(), letterhead_url)
        if pdf_bytes:
            from app.storage import BUCKET_NAME, upload_file
            remote_path = f"work_orders/{decision.id}/{uuid.uuid4()}.pdf"
            url = await upload_file(BUCKET_NAME, remote_path, pdf_bytes, "application/pdf")
            if url:
                decision.work_order_url = url

            # Email the PDF
            if decision.winning_vendor and decision.winning_vendor.contact_email:
                from app.email.resend import get_cc_emails, _apply_cc, send_batch, settings
                cc = await get_cc_emails()
                html = f"""
                <h2>Work Order Approved</h2>
                <p>Dear {decision.winning_vendor.company_name},</p>
                <p>Please find attached the official Work Order for
                <strong>{decision.requisition.title if decision.requisition else ''}</strong>.</p>
                <p>Please proceed with delivery as per agreed terms.</p>
                """
                payload = _apply_cc({
                    "from": f"Wener Supplier Management <{settings.mail_from}>",
                    "to": [decision.winning_vendor.contact_email],
                    "subject": f"Work Order: {decision.requisition.title if decision.requisition else ''}",
                    "html": html,
                    "attachments": [{
                        "filename": f"WorkOrder_{decision.id[:8].upper()}.pdf",
                        "content": list(pdf_bytes),
                    }],
                }, cc)
                await send_batch([payload])
    except Exception:
        logger.exception("Failed to generate/send legacy work order PDF for decision %s", decision_id)

    await db.commit()
    return RedirectResponse(
        url=f"/decisions/{decision_id}?success=Work+Order+Generated+and+Emailed",
        status_code=303,
    )
