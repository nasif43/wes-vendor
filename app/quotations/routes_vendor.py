import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.quotations.models import Quotation
from app.requisitions.models import RequisitionVendor
from app.storage import BUCKET_NAME, upload_file

def _generate_quotation_pdf(form_data: dict | None, req_title: str, vendor_name: str) -> bytes | None:
    """Generate quotation PDF from form data. Returns None on failure."""
    try:
        from weasyprint import HTML
        table_html = ""
        if form_data and form_data.get("items"):
            rows = []
            grand_total = 0.0
            for item in form_data["items"]:
                qty = item.get("qty", 0)
                item_price = item.get("price", 0)
                total = float(qty) * float(item_price)
                grand_total += total
                rows.append(
                    f"<tr>"
                    f"<td style='border:1px solid #ccc;padding:6px'>{item.get('name','')}</td>"
                    f"<td style='border:1px solid #ccc;padding:6px'>{item.get('description','')}</td>"
                    f"<td style='border:1px solid #ccc;padding:6px;text-align:center'>{qty}</td>"
                    f"<td style='border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace'>৳{float(item_price):.2f}</td>"
                    f"<td style='border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace;font-weight:700'>৳{total:.2f}</td>"
                    f"</tr>"
                )
            table_html = (
                "<table style='border-collapse:collapse;width:100%;font-size:12px;margin-top:16px;'>"
                "<thead style='background:#e2e8f0;'><tr>"
                "<th style='border:1px solid #ccc;padding:6px;'>Item</th>"
                "<th style='border:1px solid #ccc;padding:6px;'>Description</th>"
                "<th style='border:1px solid #ccc;padding:6px;'>Qty</th>"
                "<th style='border:1px solid #ccc;padding:6px;'>Unit Price</th>"
                "<th style='border:1px solid #ccc;padding:6px;'>Total</th>"
                "</tr></thead><tbody>"
                + "".join(rows)
                + f"</tbody><tfoot><tr>"
                f"<td colspan='4' style='border:1px solid #ccc;padding:6px;text-align:right;font-weight:700;'>Grand Total:</td>"
                f"<td style='border:1px solid #ccc;padding:6px;text-align:right;font-family:monospace;font-weight:700;'>৳{grand_total:.2f}</td>"
                f"</tr></tfoot></table>"
            )

        total_price = form_data.get("price", 0) if form_data else 0
        delivery_days = form_data.get("delivery_days", "N/A") if form_data else "N/A"
        html_content = f"""
        <!DOCTYPE html><html>
        <head><meta charset="utf-8">
        <style>@page{{margin:40px;}} body{{font-family:'Helvetica Neue',Arial,sans-serif;color:#1a1a1a;line-height:1.5;}}
        h1{{font-size:20px;border-bottom:2px solid #333;padding-bottom:6px;margin-bottom:14px;}}
        table.meta{{width:100%;font-size:13px;margin-bottom:12px;}} table.meta td{{padding:3px 0;}}
        </style></head>
        <body>
        <h1>Quotation</h1>
        <table class="meta">
        <tr><td><b>Requisition:</b> {req_title}</td><td><b>Supplier:</b> {vendor_name}</td></tr>
        <tr><td><b>Total Price:</b> ৳{float(total_price):.2f}</td><td><b>Delivery:</b> {delivery_days} days</td></tr>
        </table>
        {table_html}
        </body></html>
        """
        return HTML(string=html_content).write_pdf()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("PDF generation failed: %s", exc)
        return None

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
        
    if link.requisition and link.requisition.status in ('cancelled', 'rejected'):
        return templates.TemplateResponse(
            request, "quotations/vendor_invalid.html", status_code=403
        )
        
    if link.status == 'cancelled':
        return templates.TemplateResponse(
            request, "quotations/vendor_invalid.html", status_code=403
        )

    supplier_items = None  # None means show all items
    if link.negotiation_version == 2 and link.shortlisted_items:
        from app.requisitions.models import ShortlistedItem
        supplier_items = []
        req_items = link.requisition.items or [] if link.requisition else []
        for si in sorted(link.shortlisted_items, key=lambda x: x.item_index):
            if si.item_index < len(req_items):
                item = dict(req_items[si.item_index])
                item['shortlisted_qty'] = float(si.shortlisted_qty)
                item['original_index'] = si.item_index
                supplier_items.append(item)

    if link.quotation:
        return templates.TemplateResponse(
            request,
            "quotations/vendor_thanks.html",
            {"vendor": link.vendor, "req": link.requisition, "supplier_items": supplier_items},
        )

    return templates.TemplateResponse(
        request,
        "quotations/vendor_form.html",
        {"link": link, "vendor": link.vendor, "req": link.requisition, "token": token, "supplier_items": supplier_items},
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
        
    if link.requisition and link.requisition.status in ('cancelled', 'rejected'):
        return templates.TemplateResponse(
            request, "quotations/vendor_invalid.html", status_code=403
        )
        
    if link.status == 'cancelled':
        return templates.TemplateResponse(
            request, "quotations/vendor_invalid.html", status_code=403
        )

    if link.quotation:
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
        link.vendor.is_temporary = False  # They've identified themselves — no longer unlisted
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
        item_original_indices = req_form.getlist("item_original_index[]")
        items = []
        if item_prices and link.requisition and link.requisition.items:
            req_items = link.requisition.items
            if link.negotiation_version == 2 and link.shortlisted_items:
                # v2: only the shortlisted items are shown
                shortlisted_sorted = sorted(link.shortlisted_items, key=lambda x: x.item_index)
                visible_items = [
                    req_items[si.item_index] 
                    for si in shortlisted_sorted 
                    if si.item_index < len(req_items)
                ]
                for item, p in zip(visible_items, item_prices):
                    items.append({
                        "name": item.get("name"),
                        "description": item.get("description"),
                        "qty": item.get("shortlisted_qty", item.get("qty")),
                        "price": float(p) if p else 0.0
                    })
            else:
                # v1: all items shown
                for item, p in zip(req_items, item_prices):
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

    quote_ver = 2 if link.negotiation_version == 2 else 1

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
                notes=f"Quotation submitted by supplier {link.vendor.company_name if link.vendor else 'Supplier'}",
            )
    await db.flush()

    # ── Audit log for Quotation Submission ─────────────────────────────────────
    from app.audit.models import AuditLog
    vendor_display = link.vendor.company_name if link.vendor else "Supplier"
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



    # Send notification emails
    try:
        from app.email.resend import build_submission_notification, build_submission_confirmation, send_batch
        email_params = []

        # Generate PDF (best-effort, email sends even without it)
        pdf_bytes = _generate_quotation_pdf(
            form_data,
            req_title=link.requisition.title if link.requisition else "Quotation",
            vendor_name=link.vendor.company_name if link.vendor else "Supplier",
        )

        if link.requisition and link.requisition.creator and link.requisition.creator.email:
            view_url = f"{str(request.base_url).rstrip('/')}/quotations/detail/{link.id}"
            
            # Enforce blind bidding: do not send the PDF attachment if the creator is blind to pricing
            is_blind = False
            if hasattr(link.requisition.creator, "is_procurement_blind"):
                is_blind = link.requisition.creator.is_procurement_blind
                
            email_params.append(
                await build_submission_notification(
                    to=link.requisition.creator.email,
                    vendor_name=link.vendor.company_name if link.vendor else "Supplier",
                    requisition_title=link.requisition.title,
                    view_url=view_url,
                    pdf_bytes=None if is_blind else pdf_bytes,
                )
            )

        if link.vendor and link.vendor.contact_email:
            email_params.append(
                await build_submission_confirmation(
                    to=link.vendor.contact_email,
                    vendor_name=link.vendor.contact_person or link.vendor.company_name,
                    requisition_title=link.requisition.title if link.requisition else "Quotation",
                )
            )

        if email_params:
            await send_batch(email_params)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to send submission emails: %s", e)

    await db.commit()
    return RedirectResponse(url=f"/vendor-quote/{token}", status_code=303)
