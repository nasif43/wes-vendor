from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserProfile
from app.database import get_db
from app.dependencies import get_current_user
from app.requisitions.models import Requisition, RequisitionVendor
from app.settings.models import SystemSettings

router = APIRouter()


@router.get("/inbox", response_class=HTMLResponse)
async def quotation_inbox(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    if not user.can_see_quotes:
        await db.commit()
        return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)

    from app.requisitions.models import RequisitionStatus
    result = await db.execute(
        select(Requisition)
        .where(Requisition.status == RequisitionStatus.IN_PROGRESS)
        .order_by(Requisition.created_at.desc())
    )
    requisitions = result.scalars().all()
    return templates.TemplateResponse(
        request, "quotations/inbox.html", {"user": user, "requisitions": requisitions}
    )


@router.get("/detail/{requisition_vendor_id}", response_class=HTMLResponse)
async def quotation_detail(
    request: Request,
    requisition_vendor_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(RequisitionVendor)
        .options(
            selectinload(RequisitionVendor.requisition),
            selectinload(RequisitionVendor.vendor),
            selectinload(RequisitionVendor.quotations),
        )
        .where(RequisitionVendor.id == requisition_vendor_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        await db.commit()
        return RedirectResponse(url="/requisitions", status_code=303)

    if not (user.can_see_all_requisitions or (link.requisition and link.requisition.created_by == user.id)):
        await db.commit()
        return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)

    hide_price = user.is_procurement_blind
    return templates.TemplateResponse(
        request, "quotations/detail.html", {"user": user, "link": link, "hide_price": hide_price}
    )


@router.post("/detail/{requisition_vendor_id}/status")
async def update_quotation_status(
    requisition_vendor_id: str,
    status: str = Form(...),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.can_see_quotes:
        await db.commit()
        return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)

    valid_statuses = {"pending", "submitted", "accepted", "flagged"}
    clean_status = status.strip().lower()
    if clean_status not in valid_statuses:
        await db.commit()
        return RedirectResponse(
            url=f"/quotations/detail/{requisition_vendor_id}?error=Invalid+status", status_code=303
        )

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(RequisitionVendor)
        .options(selectinload(RequisitionVendor.requisition))
        .where(RequisitionVendor.id == requisition_vendor_id)
    )
    link = result.scalar_one_or_none()
    if link:
        if not (user.can_see_all_requisitions or (link.requisition and link.requisition.created_by == user.id)):
            await db.commit()
            return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)
        old_status = link.status
        link.status = clean_status
        from app.audit.service import log_action
        await log_action(
            db,
            actor=user,
            action="QUOTATION_STATUS_UPDATED",
            entity_type="requisition_vendor",
            entity_id=link.id,
            entity_label=link.requisition.title if link.requisition else "Quotation Link",
            notes=f"Quotation status updated from {old_status} -> {clean_status} for vendor {link.vendor.company_name if link.vendor else ''}",
        )
        await db.flush()

    await db.commit()
    return RedirectResponse(
        url=f"/quotations/detail/{requisition_vendor_id}?success=1", status_code=303
    )


@router.post("/detail/{requisition_vendor_id}/forward-cc")
async def forward_quotation_to_cc(
    requisition_vendor_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    from app.email.resend import get_cc_emails, send_batch, settings as email_settings
    from app.quotations.routes_vendor import _generate_quotation_pdf
    from app.audit.service import log_action

    if not user.can_see_quotes:
        await db.commit()
        return RedirectResponse(url="/quotations/inbox?error=Permission+denied", status_code=303)

    result = await db.execute(
        select(RequisitionVendor)
        .options(
            selectinload(RequisitionVendor.vendor),
            selectinload(RequisitionVendor.requisition),
            selectinload(RequisitionVendor.quotations),
        )
        .where(RequisitionVendor.id == requisition_vendor_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        await db.commit()
        return RedirectResponse(url="/quotations/inbox?error=Quotation+link+not+found", status_code=303)

    cc = await get_cc_emails()
    if not cc:
        await db.commit()
        return RedirectResponse(
            url=f"/quotations/detail/{requisition_vendor_id}?error=No+CC+recipients+configured.+Add+management+emails+in+Settings+first.",
            status_code=303,
        )

    # Check if quote is submitted
    if not link.quotation and link.status != "submitted":
        await db.commit()
        return RedirectResponse(
            url=f"/quotations/detail/{requisition_vendor_id}?error=No+quotation+submitted+by+this+supplier+yet.",
            status_code=303,
        )
    form_data = link.quotation.form_data if (link.quotation and link.quotation.form_data) else {}

    vendor_name = link.vendor.company_name if link.vendor else "Supplier"
    req_title = link.requisition.title if link.requisition else "Quotation"
    view_url = f"{str(request.base_url).rstrip('/')}/quotations/detail/{link.id}"

    pdf_bytes = _generate_quotation_pdf(
        form_data,
        req_title=req_title,
        vendor_name=vendor_name,
    )

    submitted_str = "Recent"
    if link.quotation and link.quotation.submitted_at:
        try:
            from zoneinfo import ZoneInfo
            from datetime import timezone as _tz, timedelta as _td
            dt = link.quotation.submitted_at
            dhaka = dt.astimezone(ZoneInfo("Asia/Dhaka")) if dt.tzinfo else dt.replace(tzinfo=_tz.utc).astimezone(ZoneInfo("Asia/Dhaka"))
            submitted_str = dhaka.strftime("%B %d, %Y at %I:%M %p BST")
        except Exception:
            submitted_str = link.quotation.submitted_at.strftime("%B %d, %Y (%I:%M %p)")

    compare_url = f"{str(request.base_url).rstrip('/')}/quotations/compare/{link.requisition_id}"
    html = f"""
    <h2>Quotation Copy: {vendor_name}</h2>
    <p>Submitted quotation copy forwarded for requisition: <strong>{req_title}</strong>.</p>
    <table style="font-family:sans-serif;font-size:13px;margin:16px 0;line-height:1.6;">
      <tr><td style="padding:4px 8px;color:#666;">Supplier:</td><td style="padding:4px 8px;font-weight:bold;">{vendor_name}</td></tr>
      <tr><td style="padding:4px 8px;color:#666;">Contact:</td><td style="padding:4px 8px;">{link.vendor.contact_person or '—'} ({link.vendor.contact_email or '—'})</td></tr>
      <tr><td style="padding:4px 8px;color:#666;">Negotiation Round:</td><td style="padding:4px 8px;font-weight:bold;">Round {link.negotiation_version}</td></tr>
      <tr><td style="padding:4px 8px;color:#666;">Submitted At:</td><td style="padding:4px 8px;">{submitted_str}</td></tr>
      <tr><td style="padding:4px 8px;color:#666;">Forwarded By:</td><td style="padding:4px 8px;">{user.full_name} ({user.email})</td></tr>
    </table>
    <div style="margin: 20px 0 16px 0;">
      <a href="{compare_url}" style="display:inline-block;background:#1d4ed8;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-weight:700;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        📊 Compare All Quotations Side-by-Side
      </a>
    </div>
    <p><a href="{view_url}" style="font-size:13px;color:#2563eb;">View this specific quotation details in portal &rarr;</a></p>
    <p style="font-size:12px;color:#888;margin-top:20px;">The official quotation summary PDF is attached.</p>
    """

    payload = {
        "from": f"Wener Supplier Management <{email_settings.mail_from}>",
        "to": cc,
        "subject": f"Quotation Copy: {req_title} - {vendor_name}",
        "html": html,
    }
    if pdf_bytes:
        payload["attachments"] = [{
            "filename": f"Quotation_{vendor_name.replace(' ', '_')}.pdf",
            "content": list(pdf_bytes),
            "content_type": "application/pdf"
        }]

    sent = await send_batch([payload])
    if not sent:
        await db.commit()
        return RedirectResponse(
            url=f"/quotations/detail/{requisition_vendor_id}?error=Failed+to+forward+email+via+Resend.+Check+Resend+API+key+or+quota.",
            status_code=303,
        )

    await log_action(
        db,
        actor=user,
        action="QUOTATION_FORWARDED_TO_CC",
        entity_type="requisition_vendor",
        entity_id=link.id,
        entity_label=req_title,
        notes=f"Forwarded quotation copy for {vendor_name} to CCs: {', '.join(cc)} by {user.full_name}.",
    )
    await db.flush()
    await db.commit()

    referer = request.headers.get("referer") or ""
    if link.requisition_id and f"/requisitions/{link.requisition_id}" in referer:
        return RedirectResponse(
            url=f"/requisitions/{link.requisition_id}?success=Quotation+copy+and+PDF+for+{vendor_name.replace(' ', '+')}+forwarded+to+CCs",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/quotations/detail/{requisition_vendor_id}?success=Quotation+copy+and+PDF+forwarded+to+CCs",
        status_code=303,
    )




@router.get("/compare/{req_id}", response_class=HTMLResponse)
async def compare_quotations(
    request: Request,
    req_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    if not user.can_see_quotes:
        await db.commit()
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        await db.commit()
        return RedirectResponse(url="/requisitions", status_code=303)

    if not (user.can_see_all_requisitions or req.created_by == user.id):
        await db.commit()
        return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)

    from app.decisions.models import Decision

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(RequisitionVendor)
        .options(
            selectinload(RequisitionVendor.vendor),
            selectinload(RequisitionVendor.quotations),
            selectinload(RequisitionVendor.shortlisted_items),
        )
        .where(RequisitionVendor.requisition_id == req_id)
    )
    links = result.scalars().all()

    dec_res = await db.execute(
        select(Decision).where(Decision.requisition_id == req_id)
    )
    decision = dec_res.scalar_one_or_none()

    # Build deduplicated vendor map: prefer v2 over v1 as the "active" card.
    # Also attach full quote history (all versions) per vendor_id for the collapsible panel.
    vendor_map: dict = {}  # vendor_id -> {"active": link, "history": [link, ...]}
    for link in links:
        if not link.quotation:
            continue  # skip pending / non-submitted
        vid = link.vendor_id
        if vid not in vendor_map:
            vendor_map[vid] = {"active": link, "history": [link]}
        else:
            vendor_map[vid]["history"].append(link)
            # v2 always wins as the active card
            if link.negotiation_version > vendor_map[vid]["active"].negotiation_version:
                vendor_map[vid]["active"] = link

    # Sort each vendor's history newest-first, then sort vendors by latest submission date desc
    def latest_submitted_at(entry):
        dates = [
            q.submitted_at
            for lnk in entry["history"]
            for q in lnk.quotations
            if q.submitted_at
        ]
        return max(dates) if dates else None

    for entry in vendor_map.values():
        entry["history"].sort(key=lambda l: l.negotiation_version, reverse=True)

    vendor_entries = sorted(
        vendor_map.values(),
        key=lambda e: latest_submitted_at(e) or __import__('datetime').datetime.min,
        reverse=True,
    )

    # Flat list of active links (for the shortlist matrix, backward-compat)
    active_links = [e["active"] for e in vendor_entries]

    # Fetch letterheads
    letterheads = {}
    for slot in ["1", "2", "3", "4"]:
        url_row = await db.get(SystemSettings, f"letterhead_{slot}")
        if url_row and url_row.value:
            name_row = await db.get(SystemSettings, f"letterhead_{slot}_name")
            letterheads[slot] = name_row.value if name_row else f"Letterhead {slot}"

    return templates.TemplateResponse(
        request, "quotations/compare.html", {
            "user": user,
            "req": req,
            "links": links,
            "vendor_entries": vendor_entries,
            "active_links": active_links,
            "decision": decision,
            "letterheads": letterheads,
        }
    )

