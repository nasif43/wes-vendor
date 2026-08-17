from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserProfile
from app.database import get_db
from app.dependencies import get_current_user
from app.requisitions.models import Requisition, RequisitionVendor

router = APIRouter()


@router.get("/inbox", response_class=HTMLResponse)
async def quotation_inbox(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    if not user.can_see_quotes:
        return RedirectResponse(url="/?error=Permission+denied", status_code=303)

    result = await db.execute(
        select(Requisition)
        .where(Requisition.status != "draft")
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

    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.id == requisition_vendor_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        return RedirectResponse(url="/quotations/inbox", status_code=303)

    return templates.TemplateResponse(
        request, "quotations/detail.html", {"user": user, "link": link}
    )


@router.post("/detail/{requisition_vendor_id}/status")
async def update_quotation_status(
    requisition_vendor_id: str,
    status: str = Form(...),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.can_see_quotes:
        return RedirectResponse(url="/?error=Permission+denied", status_code=303)

    valid_statuses = {"pending", "submitted", "accepted", "flagged"}
    clean_status = status.strip().lower()
    if clean_status not in valid_statuses:
        return RedirectResponse(
            url=f"/quotations/detail/{requisition_vendor_id}?error=Invalid+status", status_code=303
        )

    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.id == requisition_vendor_id)
    )
    link = result.scalar_one_or_none()
    if link:
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

    return RedirectResponse(
        url=f"/quotations/detail/{requisition_vendor_id}?success=1", status_code=303
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
        return RedirectResponse(url="/?error=Permission+denied", status_code=303)

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/quotations/inbox", status_code=303)

    from app.decisions.models import Decision

    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.requisition_id == req_id)
    )
    links = result.scalars().all()

    dec_res = await db.execute(
        select(Decision).where(Decision.requisition_id == req_id)
    )
    decision = dec_res.scalar_one_or_none()

    return templates.TemplateResponse(
        request, "quotations/compare.html", {"user": user, "req": req, "links": links, "decision": decision}
    )

