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
    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.id == requisition_vendor_id)
    )
    link = result.scalar_one_or_none()
    if link:
        link.status = status
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

    result = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.requisition_id == req_id)
    )
    links = result.scalars().all()

    return templates.TemplateResponse(
        request, "quotations/compare.html", {"user": user, "req": req, "links": links}
    )
