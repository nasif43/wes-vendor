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
    from app.decisions.models import Decision

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if not user.can_perform_qc:
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303
        )

    # Build receive_items from winning quotation form_data
    receive_items = []
    dec_res = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    dec = dec_res.scalar_one_or_none()

    if dec:
        from app.requisitions.models import RequisitionVendor
        wv_res = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.requisition_id == req_id,
                RequisitionVendor.vendor_id == dec.winning_vendor_id,
            ).order_by(RequisitionVendor.created_at.desc())
        )
        winning_link = wv_res.scalars().first()
        if winning_link and winning_link.quotation and winning_link.quotation.form_data:
            form_data = winning_link.quotation.form_data
            if form_data.get("items"):
                for item in form_data["items"]:
                    receive_items.append({
                        "name": item.get("name", "Item"),
                        "description": item.get("description", ""),
                        "ordered_qty": item.get("qty", 0),
                        "unit_price": item.get("price", 0),
                    })

    # Fallback: use requisition items if no quotation data
    if not receive_items and req.items:
        for item in req.items:
            receive_items.append({
                "name": item.get("name", "Item"),
                "description": item.get("description", ""),
                "ordered_qty": item.get("qty", 0),
                "unit_price": 0,  # No price data available
            })

    return templates.TemplateResponse(
        request,
        "requisitions/receive.html",
        {"req": req, "user": user, "receive_items": receive_items}
    )


@router.post("/{req_id}/receive")
async def receive_requisition_submit(
    req_id: str,
    request: Request,
    invoice_number: str = Form(...),
    qc_done: bool = Form(False),
    qc_number: str = Form(None),
    receiver_number: str = Form(None),
    delivery_photo: UploadFile = File(None),
    invoice_file: UploadFile = File(None),
    letterhead_slot: str = Form(None),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates  # noqa: F401
    from app.storage import BUCKET_NAME, upload_file
    from app.requisitions.models import ReceivedItem
    from app.decisions.models import Decision

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if not user.can_perform_qc:
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303
        )

    # Parse per-item form data
    form_data = await request.form()
    item_names = form_data.getlist("item_name[]")
    ordered_qtys = form_data.getlist("ordered_qty[]")
    received_qtys = form_data.getlist("received_qty[]")
    rejected_qtys = form_data.getlist("rejected_qty[]")
    unit_prices = form_data.getlist("unit_price[]")
    rejection_reasons = form_data.getlist("rejection_reason[]")
    item_indices = form_data.getlist("item_index[]")

    # Handle delivery photo upload
    final_delivery_image_url = ""
    if delivery_photo and delivery_photo.filename:
        photo_bytes = await delivery_photo.read()
        if len(photo_bytes) > 0:
            ext = delivery_photo.filename.split(".")[-1].lower() if "." in delivery_photo.filename else "jpg"
            remote_path = f"deliveries/{req.id}/{uuid.uuid4()}.{ext}"
            content_type = delivery_photo.content_type or "image/jpeg"
            uploaded_url = await upload_file(BUCKET_NAME, remote_path, photo_bytes, content_type)
            if uploaded_url:
                final_delivery_image_url = uploaded_url

    # Handle invoice file upload (manual invoice, optional)
    manual_invoice_url = ""
    if invoice_file and invoice_file.filename:
        inv_bytes = await invoice_file.read()
        if len(inv_bytes) > 0:
            ext = invoice_file.filename.split(".")[-1].lower() if "." in invoice_file.filename else "pdf"
            remote_path = f"invoices/{req.id}/{uuid.uuid4()}.{ext}"
            content_type = invoice_file.content_type or "application/pdf"
            uploaded_url = await upload_file(BUCKET_NAME, remote_path, inv_bytes, content_type)
            if uploaded_url:
                manual_invoice_url = uploaded_url

    # Create ReceivedItem rows
    received_items_objs = []
    invoice_line_items = []
    total_ordered = 0.0
    total_received = 0.0
    total_rejected = 0.0
    grand_total = 0.0

    for i, name in enumerate(item_names):
        try:
            idx = int(item_indices[i]) if i < len(item_indices) else i
            ordered = float(ordered_qtys[i]) if i < len(ordered_qtys) else 0.0
            received = float(received_qtys[i]) if i < len(received_qtys) else ordered
            rejected = float(rejected_qtys[i]) if i < len(rejected_qtys) else max(0.0, ordered - received)
            unit_price = float(unit_prices[i]) if i < len(unit_prices) else 0.0
            reason = rejection_reasons[i] if i < len(rejection_reasons) else ""
        except (ValueError, IndexError):
            continue

        line_total = received * unit_price
        grand_total += line_total
        total_ordered += ordered
        total_received += received
        total_rejected += rejected

        ri = ReceivedItem(
            requisition_id=req_id,
            item_index=idx,
            item_name=name,
            ordered_qty=ordered,
            received_qty=received,
            rejected_qty=rejected,
            unit_price=unit_price,
            rejection_reason=reason.strip() or None,
        )
        db.add(ri)
        received_items_objs.append(ri)
        invoice_line_items.append({
            "name": name,
            "ordered_qty": ordered,
            "received_qty": received,
            "rejected_qty": rejected,
            "unit_price": unit_price,
            "line_total": line_total,
            "rejection_reason": reason,
        })

    await db.flush()

    # Find winning work order (if any) for timer stop
    wo = None
    try:
        from app.work_orders.models import WorkOrder
        wo_res = await db.execute(
            select(WorkOrder).where(WorkOrder.requisition_id == req_id)
            .order_by(WorkOrder.issued_at.desc())
        )
        wo = wo_res.scalars().first()
        if wo and qc_done:
            from datetime import timezone
            wo.delivery_completed_at = datetime.now(timezone.utc)
            wo.status = "closed"
    except Exception:
        logger.warning("Could not find/update work order for req %s", req_id)

    # Create supplier rating
    try:
        if wo and qc_done and received_items_objs:
            from app.work_orders.service import create_supplier_rating
            await create_supplier_rating(
                db,
                work_order=wo,
                received_items=received_items_objs,
                rated_by_id=user.id,
            )
    except Exception:
        logger.exception("Failed to create supplier rating for req %s", req_id)

    # Generate invoice PDF
    invoice_pdf_url = manual_invoice_url
    try:
        from app.settings.models import SystemSettings
        letterhead_url = None
        if letterhead_slot:
            lh_row = await db.get(SystemSettings, f"letterhead_{letterhead_slot}")
            if lh_row:
                letterhead_url = lh_row.value

        # Winning supplier info
        winner_name = "N/A"
        dec_res = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
        dec = dec_res.scalar_one_or_none()
        if dec and dec.winning_vendor:
            winner_name = dec.winning_vendor.company_name
        elif wo and wo.vendor:
            winner_name = wo.vendor.company_name

        bg_style = f"background-image: url('{letterhead_url}'); background-size: cover;" if letterhead_url else ""
        rows_html = ""
        for li in invoice_line_items:
            strike = "text-decoration: line-through; color: #999;" if li["rejected_qty"] > 0 else ""
            rows_html += (
                f"<tr>"
                f"<td style='border:1px solid #ccc;padding:6px'>{li['name']}</td>"
                f"<td style='border:1px solid #ccc;padding:6px;text-align:center'>{li['ordered_qty']}</td>"
                f"<td style='border:1px solid #ccc;padding:6px;text-align:center;color:#16a34a;font-weight:600'>{li['received_qty']}</td>"
                f"<td style='border:1px solid #ccc;padding:6px;text-align:center;color:#dc2626'>{li['rejected_qty']}</td>"
                f"<td style='border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace'>৳{li['unit_price']:.2f}</td>"
                f"<td style='border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace;font-weight:700'>৳{li['line_total']:.2f}</td>"
                f"<td style='border:1px solid #ccc;padding:6px;font-size:11px;color:#666'>{li['rejection_reason'] or ''}</td>"
                f"</tr>"
            )

        from datetime import datetime as _dt, timezone as _tz
        invoice_date = _dt.now(_tz.utc).strftime("%B %d, %Y")
        html_content = f"""
        <!DOCTYPE html><html>
        <head><meta charset="utf-8">
        <style>@page{{margin:40px;}} body{{{bg_style}font-family:'Helvetica Neue',Arial,sans-serif;color:#1a1a1a;line-height:1.5;}}
        .wrap{{background:rgba(255,255,255,0.93);padding:32px;border-radius:8px;}}
        h1{{font-size:22px;border-bottom:2px solid #1a1a1a;padding-bottom:8px;margin-bottom:16px;}}
        table.meta{{width:100%;font-size:13px;margin-bottom:16px;}} table.meta td{{padding:3px 0;}}
        table.items{{border-collapse:collapse;width:100%;font-size:12px;margin-top:12px;}}
        table.items th{{border:1px solid #ccc;padding:7px;background:#e2e8f0;font-size:11px;}}
        table.items tfoot td{{font-weight:700;background:#f8fafc;}}
        .footer{{margin-top:24px;font-size:11px;color:#666;text-align:center;}}
        </style></head>
        <body><div class="wrap">
        <p style="font-size:11px;color:#666;margin-bottom:4px">Invoice No: {invoice_number} | Date: {invoice_date}</p>
        <h1>Invoice</h1>
        <table class="meta">
        <tr><td><b>Requisition:</b> {req.title}</td><td><b>Supplier:</b> {winner_name}</td></tr>
        <tr><td><b>Received by:</b> {user.full_name}</td><td><b>Invoice No:</b> {invoice_number}</td></tr>
        </table>
        <table class="items">
        <thead><tr><th>Item</th><th>Ordered</th><th style="color:#16a34a">Received</th><th style="color:#dc2626">Rejected</th><th>Unit Price</th><th>Line Total</th><th>Notes</th></tr></thead>
        <tbody>{rows_html}</tbody>
        <tfoot><tr><td colspan="5" style="text-align:right;border:1px solid #ccc;padding:6px">TOTAL PAYABLE:</td>
        <td style="border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace">৳{grand_total:.2f}</td>
        <td style="border:1px solid #ccc;padding:6px"></td></tr></tfoot>
        </table>
        <p class="footer">This invoice is system-generated based on goods received and QC-accepted quantities only.<br>
        Rejected items ({total_rejected:.0f} units) are excluded from payment.</p>
        </div></body></html>
        """
        from weasyprint import HTML as WP
        pdf_bytes = WP(string=html_content).write_pdf()
        if pdf_bytes:
            remote_path = f"invoices/{req.id}/{uuid.uuid4()}.pdf"
            url = await upload_file(BUCKET_NAME, remote_path, pdf_bytes, "application/pdf")
            if url:
                invoice_pdf_url = url
                # Email invoice to CC list
                try:
                    from app.email.resend import get_cc_emails, _apply_cc, send_batch, settings as email_settings
                    cc = await get_cc_emails()
                    html_email = f"""<h2>Invoice Generated</h2>
                    <p>The invoice for <strong>{req.title}</strong> has been generated.</p>
                    <p>Supplier: {winner_name} | Total: ৳{grand_total:.2f}</p>
                    <p>Invoice Number: {invoice_number}</p>"""
                    payload = _apply_cc({
                        "from": f"Wener Supplier Management <{email_settings.mail_from}>",
                        "to": cc[:1] if cc else [email_settings.mail_from],
                        "subject": f"Invoice: {req.title} — ৳{grand_total:.2f}",
                        "html": html_email,
                        "attachments": [{"filename": f"Invoice_{invoice_number}.pdf", "content": list(pdf_bytes)}],
                    }, cc[1:] if len(cc) > 1 else [])
                    await send_batch([payload])
                except Exception:
                    logger.exception("Failed to email invoice PDF")
    except Exception:
        logger.exception("Failed to generate invoice PDF for req %s", req_id)

    # Update requisition fields
    from datetime import timezone
    req.invoice_number = invoice_number
    req.invoice_url = invoice_pdf_url
    req.received_pieces = int(total_received)
    req.qc_number = qc_number
    req.receiver_number = receiver_number
    req.received_at = datetime.now(timezone.utc)
    req.delivery_image_url = final_delivery_image_url or None
    req.qc_done = qc_done

    from app.requisitions.service import transition_requisition_status, InvalidStateTransitionError
    if qc_done:
        req.qc_done_by = user.id
        req.qc_done_at = datetime.now(UTC)
        try:
            await transition_requisition_status(
                db,
                requisition=req,
                target_status=RequisitionStatus.CLOSED,
                actor=user,
                action_name="QC_COMPLETED",
                notes=f"Invoice: {invoice_number}. QC passed. Grand total: ৳{grand_total:.2f}. Defect qty: {total_rejected:.0f} units.",
            )
        except InvalidStateTransitionError:
            req.status = RequisitionStatus.CLOSED
    else:
        try:
            await transition_requisition_status(
                db,
                requisition=req,
                target_status=RequisitionStatus.RECEIVING,
                actor=user,
                action_name="DELIVERY_RECEIVED",
                notes=f"Invoice: {invoice_number}. Partial receipt by {user.full_name}.",
            )
        except InvalidStateTransitionError:
            req.status = RequisitionStatus.RECEIVING

    await db.flush()
    await db.commit()
    return RedirectResponse(
        url=f"/requisitions/{req_id}?success=Receiving+report+submitted+and+invoice+generated",
        status_code=303,
    )

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

