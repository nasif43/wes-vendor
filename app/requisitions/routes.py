from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile, UserRole
from app.categories.models import Category
from app.database import get_db
from app.dependencies import get_current_user
from app.email.resend import build_vendor_invitation, send_batch
from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor
from app.vendors.models import Vendor

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_requisitions(
    request: Request,
    view: str = "table",
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates
    from app.decisions.models import Decision

    stmt = select(Requisition).order_by(Requisition.created_at.desc())
    if user.role == UserRole.QC_RECEIVER and not user.can_view_all_requisitions:
        # QC receiver by default focuses on orders that are placed/awaiting delivery (SUBMITTED), arrived (RECEIVED), or completed (CLOSED)
        stmt = stmt.where(Requisition.status.in_([
            RequisitionStatus.SUBMITTED,
            RequisitionStatus.RECEIVED,
            RequisitionStatus.CLOSED,
        ]))
    elif not user.can_see_all_requisitions:
        # Procurement officers only see requisitions they created unless given access to see all
        stmt = stmt.where(Requisition.created_by == user.id)

    result = await db.execute(stmt)
    requisitions = list(result.scalars().all())



    req_ids = [r.id for r in requisitions]
    decisions_map = {}
    if req_ids:
        dec_res = await db.execute(
            select(Decision).where(Decision.requisition_id.in_(req_ids))
        )
        for d in dec_res.scalars().all():
            decisions_map[d.requisition_id] = d

    items = []
    for req in requisitions:
        decision = decisions_map.get(req.id)
        
        # Determine Kanban stage:
        # 1. 'closed': QC done
        # 2. 'received': Delivery received (pending QC)
        # 3. 'submitted': Vendor selected (Decision made / awaiting delivery)
        # 4. 'in_progress': Quotes under review / vendors yet to be selected
        # 5. 'new': Vendors invited to send quotations
        # 6. 'draft': Created but not forwarded to any vendors yet
        if req.qc_done or req.status == RequisitionStatus.CLOSED:
            stage = "closed"
        elif req.status == RequisitionStatus.RECEIVED:
            stage = "received"
        elif req.status == RequisitionStatus.SUBMITTED or decision:
            stage = "submitted"
        elif req.status == RequisitionStatus.IN_PROGRESS:
            stage = "in_progress"
        elif req.status == RequisitionStatus.NEW or (req.vendor_links and len(req.vendor_links) > 0):
            stage = "new"
        else:
            stage = "draft"


        confirmed_at = decision.approved_at or decision.decided_at if decision else None
        lead_time_days = None
        if req.qc_done_at and confirmed_at:
            diff = (req.qc_done_at - confirmed_at).total_seconds() / 86400.0
            if diff >= 0:
                lead_time_days = round(diff, 1)

        items.append({
            "req": req,
            "decision": decision,
            "stage": stage,
            "confirmed_at": confirmed_at,
            "qc_done_at": req.qc_done_at,
            "lead_time_days": lead_time_days,
        })

    return templates.TemplateResponse(
        request,
        "requisitions/list.html",
        {
            "user": user,
            "requisitions": requisitions,
            "items": items,
            "view": view,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_requisition_page(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Category).order_by(Category.name))
    categories = result.scalars().all()
    return templates.TemplateResponse(
        request, "requisitions/create.html", {"user": user, "categories": categories}
    )


@router.post("")
async def create_requisition(
    request: Request,
    title: str = Form(...),
    item_description: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form(""),
    notes: str = Form(""),
    action: str = Form("continue"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    req = Requisition(
        title=title,
        item_description=item_description,
        quantity=quantity,
        unit=unit or None,
        notes=notes or None,
        status=RequisitionStatus.DRAFT,
        created_by=user.id,
    )
    db.add(req)
    await db.flush()

    # ── Audit log ──────────────────────────────────────────────────────────────
    await log_action(
        db,
        actor=user,
        action="REQUISITION_CREATED",
        entity_type="requisition",
        entity_id=req.id,
        entity_label=req.title,
        notes=f"Qty: {req.quantity} {req.unit or ''} (Draft)",
    )

    if action == "draft":
        return RedirectResponse(url=f"/requisitions/{req.id}?success=Draft+requisition+saved", status_code=303)

    return RedirectResponse(url=f"/requisitions/{req.id}/select-vendors", status_code=303)



@router.get("/{req_id}", response_class=HTMLResponse)
async def view_requisition(
    request: Request,
    req_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    return templates.TemplateResponse(
        request, "requisitions/detail.html", {"user": user, "req": req}
    )


@router.get("/{req_id}/select-vendors", response_class=HTMLResponse)
async def select_vendors_page(
    request: Request,
    req_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    result = await db.execute(
        select(Vendor).where(Vendor.is_active == True, Vendor.is_temporary == False).order_by(Vendor.company_name)
    )
    vendors = result.scalars().all()

    result = await db.execute(select(Category).order_by(Category.name))
    categories = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "requisitions/select_vendors.html",
        {"user": user, "req": req, "vendors": vendors, "categories": categories},
    )


@router.post("/{req_id}/select-vendors")
async def send_requisition(
    request: Request,
    req_id: str,
    vendor_ids: list[str] = Form([]),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if user.role not in [UserRole.PROCUREMENT, UserRole.ADMIN] and req.created_by != user.id:
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    if not vendor_ids:
        result = await db.execute(
            select(Vendor).where(Vendor.is_active == True, Vendor.is_temporary == False).order_by(Vendor.company_name)
        )
        vendors = result.scalars().all()
        result = await db.execute(select(Category).order_by(Category.name))
        categories = result.scalars().all()
        return templates.TemplateResponse(
            request,
            "requisitions/select_vendors.html",
            {
                "user": user,
                "req": req,
                "vendors": vendors,
                "categories": categories,
                "error": "Select at least one vendor",
            },
        )

    # Batch fetch selected vendors
    vendors_res = await db.execute(select(Vendor).where(Vendor.id.in_(vendor_ids)))
    vendors_map = {v.id: v for v in vendors_res.scalars().all()}

    links = []
    for vendor_id in vendor_ids:
        link = RequisitionVendor(
            requisition_id=req_id,
            vendor_id=vendor_id,
            link_sent_at=datetime.now(UTC),
            status="pending",
        )
        db.add(link)
        links.append(link)

    await db.flush()

    email_params = []
    for link in links:
        vendor = vendors_map.get(link.vendor_id)
        if vendor and vendor.contact_email:
            quote_url = f"{str(request.base_url).rstrip('/')}/vendor-quote/{link.unique_link_token}"
            email_params.append(
                await build_vendor_invitation(
                    to=vendor.contact_email,
                    vendor_name=vendor.contact_person or vendor.company_name,
                    requisition_title=req.title,
                    quote_url=quote_url,
                )
            )

    email_sent = True
    if email_params:
        email_sent = await send_batch(email_params)

    req_target_status = RequisitionStatus.NEW
    from app.requisitions.service import transition_requisition_status
    await transition_requisition_status(
        db,
        requisition=req,
        target_status=req_target_status,
        actor=user,
        action_name="VENDORS_INVITED",
        notes=f"{len(vendor_ids)} vendor(s) invited via quote link",
    )

    if not email_sent:
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Links+created+but+email+failed.+Share+links+manually.",
            status_code=303,
        )
    return RedirectResponse(url=f"/requisitions/{req_id}?success=1", status_code=303)


@router.post("/{req_id}/add-temporary-vendor")
async def add_temporary_vendor(
    req_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    temp_vendor = Vendor(
        company_name="Temporary Vendor",
        contact_email="temporary@example.com",
        is_temporary=True,
        is_active=True,
        created_by=user.id,
    )
    db.add(temp_vendor)
    await db.flush()

    link = RequisitionVendor(
        requisition_id=req_id,
        vendor_id=temp_vendor.id,
        status="pending",
    )
    db.add(link)

    # ── Audit log for Vendor ───────────────────────────────────────────────────
    await log_action(
        db,
        actor=user,
        action="TEMPORARY_VENDOR_CREATED",
        entity_type="vendor",
        entity_id=temp_vendor.id,
        entity_label=f"Unlisted Vendor ({req.title})",
        notes=f"Unlisted/Temporary vendor link created for Requisition #{req_id} by {user.full_name} ({user.email}).",
    )

    if req.status == RequisitionStatus.DRAFT:
        from app.requisitions.service import transition_requisition_status
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=RequisitionStatus.NEW,
            actor=user,
            action_name="VENDORS_INVITED",
            notes="Temporary/Unlisted vendor link created",
        )

    await db.flush()

    return RedirectResponse(url=f"/requisitions/{req_id}?success=Temporary+vendor+link+generated", status_code=303)


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
    qc_done: bool = Form(False),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates  # noqa: F401

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if not user.can_perform_qc:
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    req.invoice_number = invoice_number
    req.invoice_url = invoice_url
    req.delivery_image_url = delivery_image_url
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
    return RedirectResponse(url=f"/requisitions/{req_id}?success=Order+marked+as+received", status_code=303)

