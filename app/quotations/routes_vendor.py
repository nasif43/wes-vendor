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
    currency: str = Form(""),
    delivery_days: str = Form(""),
    payment_terms: str = Form(""),
    warranty: str = Form(""),
    notes: str = Form(""),
    quote_image: UploadFile = File(None),
    company_name: str = Form(""),
    contact_person: str = Form(""),
    phone: str = Form(""),
    contact_email: str = Form(""),
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
        form_data = {
            "price": price,
            "currency": currency,
            "delivery_days": delivery_days,
            "payment_terms": payment_terms,
            "warranty": warranty,
        }

    quotation = Quotation(
        requisition_vendor_id=link.id,
        submission_type=submission_type,
        image_url=image_url,
        form_data=form_data,
        notes=notes or None,
    )
    db.add(quotation)
    link.status = "submitted"
    if link.requisition:
        from app.requisitions.models import RequisitionStatus
        link.requisition.status = RequisitionStatus.IN_PROGRESS
    await db.flush()

    try:
        from app.email.resend import build_submission_notification, build_submission_confirmation, send_batch
        email_params = []
        
        if link.requisition and link.requisition.creator and link.requisition.creator.email:
            view_url = f"{str(request.base_url).rstrip('/')}/quotations/detail/{link.id}"
            email_params.append(
                build_submission_notification(
                    to=link.requisition.creator.email,
                    vendor_name=link.vendor.company_name,
                    requisition_title=link.requisition.title,
                    view_url=view_url,
                )
            )
            
        if link.vendor and link.vendor.contact_email:
            email_params.append(
                build_submission_confirmation(
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

    return RedirectResponse(url=f"/vendor-quote/{token}", status_code=303)
