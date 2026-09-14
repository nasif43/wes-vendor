"""
Requisition receiving, QC, and invoice generation routes.

Handles:
- Receive form (GET/POST) — tabular per-item receiving (will be enhanced in Phase 3)
- Invoice generation
- QC completion
"""
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile, UserRole
from app.database import get_db
from app.dependencies import get_current_user
from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/{req_id}/receive", response_class=HTMLResponse)
async def receive_requisition_form(
    req_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    # We allow QC_RECEIVER, ADMIN, MANAGEMENT
    if not user.can_perform_qc:
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    from app.decisions.models import Decision
    dec = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    dec_obj = dec.scalar_one_or_none()
    if not dec_obj or dec_obj.work_order_status != 'approved':
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Work+order+not+approved", status_code=303)


    return templates.TemplateResponse(
        request,
        "requisitions/receive.html",
        {"req": req, "user": user}
    )


@router.post("/{req_id}/receive")
async def receive_requisition_submit(
    req_id: str,
    request: Request,
    invoice_number: str = Form(...),
    invoice_url: str = Form(""),
    delivery_image_url: str = Form(""),
    delivery_photo: UploadFile = File(None),
    invoice_file: UploadFile = File(None),
    qc_done: bool = Form(False),
    received_pieces: int = Form(None),
    qc_number: str = Form(None),
    receiver_number: str = Form(None),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates  # noqa: F401
    from app.storage import BUCKET_NAME, upload_file

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if not user.can_perform_qc:
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    from app.decisions.models import Decision
    dec = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    dec_obj = dec.scalar_one_or_none()
    if not dec_obj or dec_obj.work_order_status != 'approved':
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Work+order+not+approved", status_code=303)


    # Handle native camera / delivery photo upload
    final_delivery_image_url = delivery_image_url
    if delivery_photo and delivery_photo.filename:
        photo_bytes = await delivery_photo.read()
        if len(photo_bytes) > 0:
            ext = delivery_photo.filename.split(".")[-1].lower() if "." in delivery_photo.filename else "jpg"
            remote_path = f"deliveries/{req.id}/{uuid.uuid4()}.{ext}"
            content_type = delivery_photo.content_type or "image/jpeg"
            uploaded_url = await upload_file(BUCKET_NAME, remote_path, photo_bytes, content_type)
            if uploaded_url:
                final_delivery_image_url = uploaded_url

    # Handle invoice file upload
    final_invoice_url = invoice_url
    if invoice_file and invoice_file.filename:
        inv_bytes = await invoice_file.read()
        if len(inv_bytes) > 0:
            ext = invoice_file.filename.split(".")[-1].lower() if "." in invoice_file.filename else "pdf"
            remote_path = f"invoices/{req.id}/{uuid.uuid4()}.{ext}"
            content_type = invoice_file.content_type or "application/pdf"
            uploaded_url = await upload_file(BUCKET_NAME, remote_path, inv_bytes, content_type)
            if uploaded_url:
                final_invoice_url = uploaded_url

    req.invoice_number = invoice_number
    req.invoice_url = final_invoice_url
    req.received_pieces = received_pieces
    req.qc_number = qc_number
    req.receiver_number = receiver_number
    from datetime import timezone
    req.received_at = datetime.now(timezone.utc)
    req.delivery_image_url = final_delivery_image_url
    req.qc_done = qc_done

    from app.requisitions.service import transition_requisition_status
    if qc_done:
        req.qc_done_by = user.id
        req.qc_done_at = datetime.now(UTC)
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=RequisitionStatus.CLOSED,
            actor=user,
            action_name="QC_COMPLETED",
            notes=f"Invoice: {invoice_number}. QC passed by {user.full_name} ({user.email}). Requisition closed.",
        )
    else:
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=RequisitionStatus.RECEIVED,
            actor=user,
            action_name="DELIVERY_RECEIVED",
            notes=f"Invoice: {invoice_number}. Delivery received by {user.full_name} ({user.email}). QC pending.",
        )

    await db.flush()
    await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}?success=Order+marked+as+received", status_code=303)

@router.get("/{req_id}/invoice", response_class=HTMLResponse)
async def generate_invoice(
    req_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Render a printable invoice for a closed/QC-passed requisition."""
    from app.main import templates
    from app.decisions.models import Decision

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    dec_res = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    decision = dec_res.scalar_one_or_none()

    # Find the winning vendor quotation
    winning_quotation = None
    if decision:
        wv_res = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.requisition_id == req_id,
                RequisitionVendor.vendor_id == decision.winning_vendor_id,
            )
        )
        winning_link = wv_res.scalar_one_or_none()
        if winning_link:
            winning_quotation = winning_link.quotation

    return templates.TemplateResponse(
        request,
        "requisitions/invoice.html",
        {
            "user": user,
            "req": req,
            "decision": decision,
            "winning_quotation": winning_quotation,
        },
    )

