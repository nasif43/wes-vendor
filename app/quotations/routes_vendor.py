import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.quotations.models import Quotation
from app.requisitions.models import RequisitionVendor
from app.storage import BUCKET_NAME, upload_file

router = APIRouter()


@router.get("/{token}", response_class=HTMLResponse)
async def vendor_quote_form(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.unique_link_token == token)
    )
    link = result.scalar_one_or_none()
    if not link:
        return templates.TemplateResponse(
            request, "quotations/vendor_invalid.html", status_code=404
        )

    if link.quotation:
        return templates.TemplateResponse(
            request,
            "quotations/vendor_thanks.html",
            {"vendor": link.vendor, "req": link.requisition},
        )

    return templates.TemplateResponse(
        request,
        "quotations/vendor_form.html",
        {"link": link, "vendor": link.vendor, "req": link.requisition, "token": token},
    )


@router.post("/{token}", response_class=HTMLResponse)
async def submit_quotation(
    request: Request,
    token: str,
    submission_type: str = Form(...),
    price: str = Form(""),
    currency: str = Form("BDT"),
    delivery_days: str = Form(""),
    payment_terms: str = Form(""),
    warranty: str = Form(""),
    notes: str = Form(""),
    quoted_quantity: str = Form(""),
    quote_image: UploadFile = File(None),
    company_name: str = Form(""),
    contact_person: str = Form(""),
    phone: str = Form(""),
    contact_email: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates
    req_form = await request.form()

    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.unique_link_token == token)
    )
    link = result.scalar_one_or_none()
    if not link:
        return templates.TemplateResponse(
            request, "quotations/vendor_invalid.html", status_code=404
        )

    if link.quotation:
        await db.commit()
    return RedirectResponse(url=f"/vendor-quote/{token}", status_code=303)

    if link.vendor and link.vendor.is_temporary:
        if not company_name or not contact_person or not phone or not contact_email:
            return templates.TemplateResponse(
                request,
                "quotations/vendor_form.html",
                {
                    "link": link,
                    "vendor": link.vendor,
                    "req": link.requisition,
                    "token": token,
                    "error": "All contact details (Company Name, Contact Person, Phone, Email) are required.",
                },
                status_code=400,
            )
        link.vendor.company_name = company_name
        link.vendor.contact_person = contact_person
        link.vendor.phone = phone
        link.vendor.contact_email = contact_email
        await db.flush()

    image_url = None
    if submission_type == "image" and quote_image:
        contents = await quote_image.read()
        ext = quote_image.filename.split(".")[-1] if "." in (quote_image.filename or "") else "jpg"
        remote_path = f"quotations/{link.id}/{uuid.uuid4()}.{ext}"
        content_type = quote_image.content_type or "image/jpeg"
        image_url = await upload_file(BUCKET_NAME, remote_path, contents, content_type)
        if not image_url:
            return templates.TemplateResponse(
                request,
                "quotations/vendor_form.html",
                {
                    "link": link,
                    "vendor": link.vendor,
                    "req": link.requisition,
                    "token": token,
                    "error": "File upload failed. Please try again.",
                },
                status_code=500,
            )

    form_data = None
    if submission_type == "form":
        item_prices = req_form.getlist("item_price[]")
        items = []
        if item_prices and link.requisition and link.requisition.items:
            for item, p in zip(link.requisition.items, item_prices):
                items.append({
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "qty": item.get("qty"),
                    "price": float(p) if p else 0.0
                })
        
        form_data = {
            "price": price,
            "items": items,
            "currency": "BDT",  # Locked globally to BDT
            "delivery_days": delivery_days,
            "payment_terms": payment_terms or None,
            "warranty": warranty or None,
        }

    # Determine quote version based on negotiation_version of the link
    quote_ver = 2 if str(link.negotiation_version or "1") == "2" else 1

    # Parse optional quoted quantity
    quoted_qty = None
    if quoted_quantity:
        try:
            quoted_qty = float(quoted_quantity)
            if quoted_qty <= 0:
                quoted_qty = None
        except (ValueError, TypeError):
            quoted_qty = None

    quotation = Quotation(
        requisition_vendor_id=link.id,
        submission_type=submission_type,
        image_url=image_url,
        form_data=form_data,
        notes=notes or None,
        quote_version=quote_ver,
        quoted_quantity=quoted_qty,
    )
    db.add(quotation)
    link.status = "submitted"
    if link.requisition:
        from app.requisitions.models import RequisitionStatus
        if link.requisition.status in (RequisitionStatus.DRAFT, RequisitionStatus.NEW):
            from app.requisitions.service import transition_requisition_status
            await transition_requisition_status(
                db,
                requisition=link.requisition,
                target_status=RequisitionStatus.IN_PROGRESS,
                actor=None,
                action_name="QUOTATION_RECEIVED",
                notes=f"Quotation submitted by vendor {link.vendor.company_name if link.vendor else 'Vendor'}",
            )
    await db.flush()

    # ── Audit log for Quotation Submission ─────────────────────────────────────
    from app.audit.models import AuditLog
    vendor_display = link.vendor.company_name if link.vendor else "Vendor"
    vendor_email = link.vendor.contact_email if link.vendor else "vendor@external"
    db.add(
        AuditLog(
            actor_name=vendor_display,
            actor_email=vendor_email,
            actor_role="vendor",
            action="QUOTATION_SUBMITTED",
            entity_type="quotation",
            entity_id=quotation.id,
            entity_label=link.requisition.title if link.requisition else "Quotation",
            notes=f"Quotation ({submission_type}) submitted by {vendor_display} for Requisition #{link.requisition_id}",
        )
    )
    await db.flush()



    try:
        from app.email.resend import build_submission_notification, build_submission_confirmation, send_batch
        email_params = []
        
        
        pdf_bytes = None
        try:
            from weasyprint import HTML
            table_html = ""
            if form_data and form_data.get("items"):
                rows = []
                grand_total = 0.0
                for item in form_data["items"]:
                    qty = item.get("qty", 0)
                    item_price = item.get("price", 0)
                    total = qty * item_price
                    grand_total += total
                    rows.append(f"<tr><td>{item.get('name', '')}</td><td>{item.get('description', '')}</td><td>{qty}</td><td>{item_price:.2f}</td><td>{total:.2f}</td></tr>")
                
                table_html = f"""
                <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 13px; text-align: left; border: 1px solid #333; margin-top: 20px;">
                  <thead style="background-color: #e2e8f0; border-bottom: 2px solid #333;">
                    <tr>
                      <th style="border: 1px solid #333;">Name</th>
                      <th style="border: 1px solid #333;">Description</th>
                      <th style="border: 1px solid #333;">Qty</th>
                      <th style="border: 1px solid #333;">Price</th>
                      <th style="border: 1px solid #333;">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {''.join(rows)}
                  </tbody>
                  <tfoot style="background-color: #f8fafc;">
                    <tr>
                      <td colspan="4" style="text-align: right; font-weight: bold; border: 1px solid #333;">Grand Total:</td>
                      <td style="font-weight: bold; border: 1px solid #333;">{grand_total:.2f}</td>
                    </tr>
                  </tfoot>
                </table>
                """
                
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
                <h1 style="border-bottom: 2px solid #333; padding-bottom: 5px;">Quotation</h1>
                <table style="width: 100%; font-size: 14px; margin-bottom: 20px;">
                    <tr><td><strong>Title:</strong> {link.requisition.title}</td><td><strong>Supplier:</strong> {link.vendor.company_name}</td></tr>
                    <tr><td><strong>Total Quote Price:</strong> {price} {currency}</td><td><strong>Delivery Days:</strong> {delivery_days}</td></tr>
                    <tr><td colspan="2"><strong>Notes:</strong> {notes}</td></tr>
                </table>
                {table_html}
            </body>
            </html>
            """
            pdf_bytes = HTML(string=html_content).write_pdf()
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to generate PDF")
            
        if link.requisition and link.requisition.creator and link.requisition.creator.email:
            view_url = f"{str(request.base_url).rstrip('/')}/quotations/detail/{link.id}"
            email_params.append(
                await build_submission_notification(
                    to=link.requisition.creator.email,
                    vendor_name=link.vendor.company_name,
                    requisition_title=link.requisition.title,
                    view_url=view_url,
                    pdf_bytes=pdf_bytes
                )
            )
            
        if link.vendor and link.vendor.contact_email:
            email_params.append(
                await build_submission_confirmation(
                    to=link.vendor.contact_email,
                    vendor_name=link.vendor.contact_person or link.vendor.company_name,
                    requisition_title=link.requisition.title,
                )
            )
            
        if email_params:
            await send_batch(email_params)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to send submission emails: %s", e)

    await db.commit()
    return RedirectResponse(url=f"/vendor-quote/{token}", status_code=303)
