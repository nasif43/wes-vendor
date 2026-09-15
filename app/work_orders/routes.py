"""
Work Order routes.
- Procurement issues work orders to winning suppliers
- Management can view work orders
- Work order PDF generated on issuance with active letterhead
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserProfile, UserRole
from app.database import get_db
from app.dependencies import get_current_user
from app.work_orders.models import WorkOrder
from app.work_orders.service import generate_work_order_pdf, send_work_order_email

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_work_orders(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates
    stmt = select(WorkOrder).order_by(WorkOrder.issued_at.desc())
    if not user.can_see_all_requisitions:
        stmt = stmt.where(WorkOrder.issued_by == user.id)
    result = await db.execute(stmt)
    work_orders = result.scalars().all()
    return templates.TemplateResponse(
        request, "work_orders/list.html", {"user": user, "work_orders": work_orders}
    )


@router.get("/{wo_id}", response_class=HTMLResponse)
async def view_work_order(
    request: Request,
    wo_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = result.scalar_one_or_none()
    if not wo:
        return RedirectResponse(url="/work-orders", status_code=303)
    return templates.TemplateResponse(
        request, "work_orders/detail.html", {"user": user, "wo": wo}
    )


@router.post("/issue/{req_id}/{rv_id}")
async def issue_work_order(
    request: Request,
    req_id: str,
    rv_id: str,
    notes: str = Form(""),
    letterhead_slot: str = Form(None),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue a work order for a winning supplier (requisition_vendor link).
    
    Called by Procurement after management selects winner.
    Generates PDF with active letterhead and emails it to the supplier.
    """
    if user.role not in [UserRole.PROCUREMENT, UserRole.ADMIN]:
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Only+Procurement+can+issue+work+orders",
            status_code=303
        )

    from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor
    from app.requisitions.service import transition_requisition_status
    from app.audit.service import log_action
    from app.settings.models import SystemSettings

    rv_result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.id == rv_id)
    )
    rv = rv_result.scalar_one_or_none()
    if not rv or rv.requisition_id != req_id:
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Supplier+link+not+found", status_code=303)

    # Fetch the decision to verify this is the actual winner
    from app.decisions.models import Decision
    decision_res = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    decision = decision_res.scalar_one_or_none()
    
    if not decision or decision.winning_vendor_id != rv.vendor_id:
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Work+orders+can+only+be+issued+to+selected+award+winners",
            status_code=303
        )

    # Check if WO already issued for this link
    existing = await db.execute(
        select(WorkOrder).where(WorkOrder.requisition_vendor_id == rv_id)
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Work+order+already+issued+for+this+supplier",
            status_code=303
        )

    letterhead_url = None
    if letterhead_slot:
        lh_row = await db.get(SystemSettings, f"letterhead_{letterhead_slot}")
        if lh_row:
            letterhead_url = lh_row.value

    wo = WorkOrder(
        requisition_id=req_id,
        vendor_id=rv.vendor_id,
        requisition_vendor_id=rv_id,
        issued_by=user.id,
        issued_at=datetime.now(UTC),
        delivery_started_at=datetime.now(UTC),
        letterhead_slot=letterhead_slot,
        notes=notes or None,
        status="issued",
    )
    db.add(wo)
    await db.flush()

    # Generate PDF
    pdf_bytes = None
    try:
        pdf_bytes = await generate_work_order_pdf(wo, letterhead_url)
        if pdf_bytes:
            from app.storage import BUCKET_NAME, upload_file
            import uuid as _uuid
            remote_path = f"work_orders/{wo.id}/{_uuid.uuid4()}.pdf"
            url = await upload_file(BUCKET_NAME, remote_path, pdf_bytes, "application/pdf")
            if url:
                wo.pdf_url = url
    except Exception:
        logger.exception("Failed to generate work order PDF for WO %s", wo.id)

    # Transition requisition status
    req_result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = req_result.scalar_one_or_none()
    if req and req.status == RequisitionStatus.AWARDED:
        await transition_requisition_status(
            db, requisition=req,
            target_status=RequisitionStatus.WORK_ORDER_ISSUED,
            actor=user,
            action_name="WORK_ORDER_ISSUED",
            notes=f"Work order issued to {rv.vendor.company_name} by {user.full_name}",
        )

    await log_action(
        db, actor=user,
        action="WORK_ORDER_ISSUED",
        entity_type="work_order",
        entity_id=wo.id,
        entity_label=f"WO for {rv.vendor.company_name if rv.vendor else rv.vendor_id}",
        notes=f"Work order issued for requisition #{req_id}",
    )

    await db.flush()
    await db.commit()

    # Send email (after commit so WO has all data)
    if pdf_bytes and rv.vendor and rv.vendor.contact_email:
        try:
            await send_work_order_email(wo, pdf_bytes)
        except Exception:
            logger.exception("Failed to email work order for WO %s", wo.id)

    return RedirectResponse(
        url=f"/requisitions/{req_id}?success=Work+order+issued+and+emailed",
        status_code=303
    )
