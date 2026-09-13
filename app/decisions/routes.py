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



@router.post("/{decision_id}/approve_work_order")
async def approve_work_order(
    decision_id: str,
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
        
    decision.work_order_status = "approved"
    
    # Generate PDF
    try:
        from weasyprint import HTML
        from app.settings.models import SystemSettings
        from app.storage import BUCKET_NAME, upload_file
        import uuid
        
        # Get active letterhead
        active_slot = await db.get(SystemSettings, "active_letterhead")
        bg_url = ""
        if active_slot:
            lh = await db.get(SystemSettings, f"letterhead_{active_slot.value}")
            if lh:
                bg_url = lh.value

        from app.requisitions.models import RequisitionVendor
        from sqlalchemy import select
        wv_res = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.requisition_id == decision.requisition_id,
                RequisitionVendor.vendor_id == decision.winning_vendor_id
            ).order_by(RequisitionVendor.created_at.desc())
        )
        winning_link = wv_res.scalars().first()

        table_html = ""
        if winning_link and winning_link.quotation and winning_link.quotation.form_data:
            form_data = winning_link.quotation.form_data
            if form_data.get("items"):
                rows = []
                grand_total = 0.0
                for item in form_data["items"]:
                    qty = item.get("qty", 0)
                    item_price = item.get("price", 0)
                    total = qty * item_price
                    grand_total += total
                    rows.append(f"<tr><td style='border: 1px solid #333; padding: 6px;'>{item.get('name', '')}</td><td style='border: 1px solid #333; padding: 6px;'>{item.get('description', '')}</td><td style='border: 1px solid #333; padding: 6px;'>{qty}</td><td style='border: 1px solid #333; padding: 6px;'>{item_price:.2f}</td><td style='border: 1px solid #333; padding: 6px;'>{total:.2f}</td></tr>")
                
                table_html = f"""
                <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 13px; text-align: left; border: 1px solid #333; margin-top: 20px; background-color: rgba(255, 255, 255, 0.9);">
                  <thead style="background-color: #e2e8f0; border-bottom: 2px solid #333;">
                    <tr>
                      <th style="border: 1px solid #333; padding: 6px;">Name</th>
                      <th style="border: 1px solid #333; padding: 6px;">Description</th>
                      <th style="border: 1px solid #333; padding: 6px;">Qty</th>
                      <th style="border: 1px solid #333; padding: 6px;">Price</th>
                      <th style="border: 1px solid #333; padding: 6px;">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(rows)}
                  </tbody>
                  <tfoot style="background-color: #f8fafc;">
                    <tr>
                      <td colspan="4" style="text-align: right; font-weight: bold; border: 1px solid #333; padding: 6px;">Grand Total:</td>
                      <td style="font-weight: bold; border: 1px solid #333; padding: 6px;">{grand_total:.2f}</td>
                    </tr>
                  </tfoot>
                </table>
                """

        bg_style = f"background-image: url({bg_url}); background-size: cover; background-position: center;" if bg_url else ""
        html_content = f"""
        <html>
        <body style="{bg_style} font-family: Arial, sans-serif; color: #333; line-height: 1.6; padding: 40px;">
            <div style="background-color: rgba(255,255,255,0.85); padding: 20px; border-radius: 8px;">
                <h1 style="border-bottom: 2px solid #333; padding-bottom: 5px;">Work Order / Purchase Order</h1>
                <table style="width: 100%; font-size: 14px; margin-bottom: 20px;">
                    <tr><td><strong>Requisition:</strong> {decision.requisition.title}</td><td><strong>Supplier:</strong> {decision.winning_vendor.company_name}</td></tr>
                </table>
                {table_html}
            </div>
        </body>
        </html>
        """
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        remote_path = f"work_orders/{decision.id}/{uuid.uuid4()}.pdf"
        url = await upload_file(BUCKET_NAME, remote_path, pdf_bytes, "application/pdf")
        if url:
            decision.work_order_url = url
            
        # Email the PDF to the winning supplier
        from app.email.resend import send_batch, get_cc_emails, _apply_cc, settings
        if decision.winning_vendor and decision.winning_vendor.contact_email:
            cc = await get_cc_emails()
            html = f"""
            <h2>Work Order Approved</h2>
            <p>Dear {decision.winning_vendor.company_name},</p>
            <p>Please find attached the official Work Order / Purchase Order for <strong>{decision.requisition.title}</strong>.</p>
            <p>You may now proceed with the delivery of the requested items.</p>
            """
            payload = {
                "from": f"Wener Supplier Management <{settings.mail_from}>",
                "to": [decision.winning_vendor.contact_email],
                "subject": f"Work Order: {decision.requisition.title}",
                "html": html,
                "attachments": [{"filename": f"WorkOrder_{decision.id}.pdf", "content": list(pdf_bytes)}]
            }
            payload = _apply_cc(payload, cc)
            await send_batch([payload])
            
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to generate or send Work Order PDF")
        
    await db.commit()
    return RedirectResponse(url=f"/decisions/{decision_id}?success=Work+Order+Generated+and+Emailed", status_code=303)
