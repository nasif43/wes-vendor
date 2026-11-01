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
from app.requisitions.models import Requisition, RequisitionStatus
from app.settings.models import SystemSettings
from app.requisitions.models import RequisitionVendor

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_requisitions(
    request: Request,
    view: str = "table",
    page: int = 1,
    page_size: int = 50,
    sort: str = "created_desc",
    search: str = "",
    status_filter: str = "",
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates
    from app.decisions.models import Decision
    from sqlalchemy import func

    stmt = select(Requisition)

    # ── Search ────────────────────────────────────────────────────────────────
    if search:
        import re
        from sqlalchemy import or_
        from app.requisitions.models import RequisitionVendor
        from app.work_orders.models import WorkOrder

        raw_search = search.strip()

        # Extract standard 36-char UUID pattern if present anywhere in the string
        uuid_match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", raw_search)

        # Clean prefixes: "Requisition #", "REQ-", "WO-", "PO-", "RV-", "#", etc.
        clean_term = raw_search
        for prefix in (
            "Requisition #", "requisition #", "Requisition:", "requisition:", "Requisition ", "requisition ",
            "REQ-", "req-", "WO-", "wo-", "PO-", "po-", "RV-", "rv-", "#"
        ):
            if clean_term.startswith(prefix):
                clean_term = clean_term[len(prefix):].strip()

        search_conditions = [
            Requisition.title.ilike(f"%{raw_search}%"),
            Requisition.item_description.ilike(f"%{raw_search}%"),
        ]

        if clean_term:
            search_conditions.append(Requisition.id.ilike(f"%{clean_term}%"))
            # If at least 6 characters, also check if it matches a quotation link or work order id
            if len(clean_term) >= 6:
                search_conditions.append(
                    Requisition.id.in_(
                        select(RequisitionVendor.requisition_id).where(RequisitionVendor.id.ilike(f"%{clean_term}%"))
                    )
                )
                search_conditions.append(
                    Requisition.id.in_(
                        select(WorkOrder.requisition_id).where(WorkOrder.id.ilike(f"%{clean_term}%"))
                    )
                )

        if uuid_match:
            exact_uuid = uuid_match.group(1).lower()
            search_conditions.append(Requisition.id.ilike(f"%{exact_uuid}%"))
            search_conditions.append(
                Requisition.id.in_(
                    select(RequisitionVendor.requisition_id).where(RequisitionVendor.id.ilike(f"%{exact_uuid}%"))
                )
            )
            search_conditions.append(
                Requisition.id.in_(
                    select(WorkOrder.requisition_id).where(WorkOrder.id.ilike(f"%{exact_uuid}%"))
                )
            )

        stmt = stmt.where(or_(*search_conditions))

    # ── Status filter ─────────────────────────────────────────────────────────
    if status_filter:
        if status_filter == "cancelled":
            stmt = stmt.where(Requisition.status.in_([RequisitionStatus.CANCELLED.value, RequisitionStatus.REJECTED.value]))
        else:
            try:
                stmt = stmt.where(Requisition.status == RequisitionStatus(status_filter).value)
            except ValueError:
                pass

    # ── Role-based visibility ──────────────────────────────────────────────────
    if user.role == UserRole.QC_RECEIVER and not user.can_view_all_requisitions:
        stmt = stmt.where(Requisition.status.in_([
            RequisitionStatus.SUBMITTED.value,
            RequisitionStatus.RECEIVED.value,
            RequisitionStatus.CLOSED.value,
        ]))
    elif not user.can_see_all_requisitions:
        stmt = stmt.where(Requisition.created_by == user.id)

    # ── Sort ──────────────────────────────────────────────────────────────────
    sort_map = {
        "created_asc": Requisition.created_at.asc(),
        "created_desc": Requisition.created_at.desc(),
        "updated_asc": Requisition.updated_at.asc(),
        "updated_desc": Requisition.updated_at.desc(),
    }
    stmt = stmt.order_by(sort_map.get(sort, Requisition.created_at.desc()))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await db.scalar(count_stmt) or 0
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    stmt = stmt.limit(page_size).offset((page - 1) * page_size)
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
        
        # Determine stage:
        if req.qc_done or req.status == RequisitionStatus.CLOSED:
            stage = "closed"
        elif req.status in (RequisitionStatus.RECEIVING, RequisitionStatus.RECEIVED):
            stage = "receiving"
        elif req.status in (RequisitionStatus.CANCELLED, RequisitionStatus.REJECTED):
            stage = "cancelled"
        elif req.status == RequisitionStatus.WORK_ORDER_ISSUED:
            stage = "work_order_issued"
        elif req.status in (RequisitionStatus.AWARDED, RequisitionStatus.SUBMITTED) or decision:
            stage = "awarded"
        elif req.status == RequisitionStatus.NEGOTIATING:
            stage = "negotiating"
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

    # UI status filter order (excludes legacy aliases and rejected)
    ui_status_list = [
        RequisitionStatus.DRAFT,
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.NEGOTIATING,
        RequisitionStatus.AWARDED,
        RequisitionStatus.WORK_ORDER_ISSUED,
        RequisitionStatus.RECEIVING,
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
    ]

    return templates.TemplateResponse(

        request,
        "requisitions/list.html",
        {
            "user": user,
            "requisitions": requisitions,
            "items": items,
            "view": view,
            "page": page,
            "total_pages": total_pages,
            "sort": sort,
            "search": search,
            "status_filter": status_filter,
            "RequisitionStatus": RequisitionStatus,
            "ui_status_list": ui_status_list,
        },
    )

@router.get("/{req_id}/edit", response_class=HTMLResponse)
async def edit_requisition_page(
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

    if not (user.has_management_authority or user.role == UserRole.ADMIN or req.created_by == user.id):
        await db.commit()
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    # Requisition cannot be edited if suppliers have already submitted quotations
    has_submitted_quotes = any(
        vl.status == "submitted" or (vl.quotations and len(vl.quotations) > 0)
        for vl in (req.vendor_links or [])
    )
    if has_submitted_quotes:
        await db.commit()
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Requisition+is+locked+because+suppliers+have+already+submitted+quotations",
            status_code=303,
        )
        

    # UI status filter order (excludes legacy aliases)
    ui_status_list = [
        RequisitionStatus.DRAFT,
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.NEGOTIATING,
        RequisitionStatus.AWARDED,
        RequisitionStatus.WORK_ORDER_ISSUED,
        RequisitionStatus.RECEIVING,
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
    ]

    return templates.TemplateResponse(

        request, "requisitions/edit.html", {"user": user, "req": req}
    )

@router.post("/{req_id}/edit")
async def update_requisition(
    request: Request,
    req_id: str,
    title: str = Form(...),
    notes: str = Form(""),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if not (user.has_management_authority or user.role == UserRole.ADMIN or req.created_by == user.id):
        await db.commit()
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    # Requisition cannot be edited if suppliers have already submitted quotations
    has_submitted_quotes = any(
        vl.status == "submitted" or (vl.quotations and len(vl.quotations) > 0)
        for vl in (req.vendor_links or [])
    )
    if has_submitted_quotes:
        await db.commit()
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Requisition+is+locked+because+suppliers+have+already+submitted+quotations",
            status_code=303,
        )
        
    form_data = await request.form()
    item_names = form_data.getlist("item_name[]")
    item_descs = form_data.getlist("item_desc[]")
    item_qtys = form_data.getlist("item_qty[]")
    item_units = form_data.getlist("item_unit[]")
    
    items = []
    total_qty = 0.0
    for i in range(len(item_names)):
        n = item_names[i].strip() if item_names[i] else ""
        if not n:
            continue
        d = item_descs[i].strip() if i < len(item_descs) else ""
        q = item_qtys[i] if i < len(item_qtys) else 0.0
        u = item_units[i].strip() if i < len(item_units) else ""
        qty = float(q) if q else 0.0
        items.append({"name": n, "description": d, "qty": qty, "unit": u})
        total_qty += qty

    req.title = title
    req.items = items
    req.quantity = total_qty
    if items and items[0].get("unit"):
        req.unit = items[0]["unit"]
    req.item_description = "Multiple items" if items else ""
    req.notes = notes or None
    
    await db.flush()
    
    await log_action(
        db,
        actor=user,
        action="REQUISITION_UPDATED",
        entity_type="requisition",
        entity_id=req.id,
        entity_label=req.title,
        notes="Requisition details/quantity updated.",
    )
    
    await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}", status_code=303)


@router.get("/new", response_class=HTMLResponse)
async def new_requisition_page(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Category).order_by(Category.name))
    categories = result.scalars().all()

    # UI status filter order (excludes legacy aliases)
    ui_status_list = [
        RequisitionStatus.DRAFT,
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.NEGOTIATING,
        RequisitionStatus.AWARDED,
        RequisitionStatus.WORK_ORDER_ISSUED,
        RequisitionStatus.RECEIVING,
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
    ]

    return templates.TemplateResponse(

        request, "requisitions/create.html", {"user": user, "categories": categories}
    )


@router.post("")
async def create_requisition(
    request: Request,
    title: str = Form(...),
    notes: str = Form(""),
    action: str = Form("continue"),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    form_data = await request.form()
    item_names = form_data.getlist("item_name[]")
    item_descs = form_data.getlist("item_desc[]")
    item_qtys = form_data.getlist("item_qty[]")
    item_units = form_data.getlist("item_unit[]")
    
    items = []
    total_qty = 0.0
    for i in range(len(item_names)):
        n = item_names[i].strip() if item_names[i] else ""
        if not n:
            continue
        d = item_descs[i].strip() if i < len(item_descs) else ""
        q = item_qtys[i] if i < len(item_qtys) else 0.0
        u = item_units[i].strip() if i < len(item_units) else ""
        qty = float(q) if q else 0.0
        items.append({"name": n, "description": d, "qty": qty, "unit": u})
        total_qty += qty

    req = Requisition(
        title=title,
        item_description="Multiple items" if items else "",
        quantity=total_qty,
        unit=items[0].get("unit") if (items and items[0].get("unit")) else None,
        items=items,
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
        await db.commit()
        return RedirectResponse(url=f"/requisitions/{req.id}?success=Draft+requisition+saved", status_code=303)

    await db.commit()
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
        await db.commit()
        return RedirectResponse(url="/requisitions", status_code=303)

    if user.role == UserRole.QC_RECEIVER and not user.can_view_all_requisitions:
        if req.status not in (RequisitionStatus.SUBMITTED.value, RequisitionStatus.RECEIVED.value, RequisitionStatus.CLOSED.value):
            await db.commit()
            return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)
    elif not user.can_see_all_requisitions and req.created_by != user.id:
        await db.commit()
        return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)

    # Fetch letterheads
    letterheads = {}
    for slot in ["1", "2", "3", "4"]:
        url_row = await db.get(SystemSettings, f"letterhead_{slot}")
        if url_row and url_row.value:
            name_row = await db.get(SystemSettings, f"letterhead_{slot}_name")
            letterheads[slot] = name_row.value if name_row else f"Letterhead {slot}"

    from app.decisions.models import Decision
    decision_res = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    decision = decision_res.scalar_one_or_none()

    from app.work_orders.models import WorkOrder
    wo_res = await db.execute(select(WorkOrder).where(WorkOrder.requisition_id == req_id))
    work_orders = wo_res.scalars().all()
    work_order_by_link = {wo.requisition_vendor_id: wo for wo in work_orders if wo.requisition_vendor_id}

    # UI status filter order (excludes legacy aliases)
    ui_status_list = [
        RequisitionStatus.DRAFT,
        RequisitionStatus.NEW,
        RequisitionStatus.IN_PROGRESS,
        RequisitionStatus.NEGOTIATING,
        RequisitionStatus.AWARDED,
        RequisitionStatus.WORK_ORDER_ISSUED,
        RequisitionStatus.RECEIVING,
        RequisitionStatus.CLOSED,
        RequisitionStatus.CANCELLED,
    ]

    return templates.TemplateResponse(
        request,
        "requisitions/detail.html",
        {
            "user": user,
            "req": req,
            "letterheads": letterheads,
            "decision": decision,
            "work_orders": work_orders,
            "work_order_by_link": work_order_by_link,
        },
    )












@router.post("/{req_id}/cancel")
async def cancel_requisition(
    req_id: str,
    reason: str = Form(""),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a requisition — available to management/admin and the original creator."""
    from app.auth.models import UserRole
    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if not (user.has_management_authority or user.role == UserRole.ADMIN or req.created_by == user.id):
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    req.rejected_reason = reason or None
    from app.requisitions.service import transition_requisition_status
    await transition_requisition_status(
        db,
        requisition=req,
        target_status=RequisitionStatus.CANCELLED,
        actor=user,
        action_name="REQUISITION_CANCELLED",
        notes=f"Cancelled by {user.full_name}. Reason: {reason or 'No reason given'}",
    )

    # Cancel all pending links and notify suppliers
    from app.email.resend import build_cancellation_notification, send_batch
    email_params = []
    if req.vendor_links:
        for link in req.vendor_links:
            if link.status == 'pending':
                link.status = 'cancelled'
                if link.vendor and link.vendor.contact_email:
                    email_params.append(
                        await build_cancellation_notification(
                            to=link.vendor.contact_email,
                            supplier_name=link.vendor.contact_person or link.vendor.company_name,
                            requisition_title=req.title,
                        )
                    )
    await db.flush()
    await db.commit()
    
    if email_params:
        try:
            await send_batch(email_params)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to send cancellation emails: %s", e)
    return RedirectResponse(url=f"/requisitions/{req_id}?success=Requisition+cancelled", status_code=303)


@router.post("/{req_id}/reject")
async def reject_requisition(
    req_id: str,
    reason: str = Form(""),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a requisition — management/admin only."""
    from app.auth.models import UserRole
    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    if not (user.has_management_authority or user.role == UserRole.ADMIN):
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    req.rejected_reason = reason or None
    from app.requisitions.service import transition_requisition_status
    await transition_requisition_status(
        db,
        requisition=req,
        target_status=RequisitionStatus.REJECTED,
        actor=user,
        action_name="REQUISITION_REJECTED",
        notes=f"Rejected by {user.full_name}. Reason: {reason or 'No reason given'}",
    )
    
    # Cancel all pending links and notify suppliers
    from app.email.resend import build_cancellation_notification, send_batch
    email_params = []
    if req.vendor_links:
        for link in req.vendor_links:
            if link.status == 'pending':
                link.status = 'cancelled'
                if link.vendor and link.vendor.contact_email:
                    email_params.append(
                        await build_cancellation_notification(
                            to=link.vendor.contact_email,
                            supplier_name=link.vendor.contact_person or link.vendor.company_name,
                            requisition_title=req.title,
                        )
                    )
    await db.flush()
    await db.commit()

    if email_params:
        try:
            await send_batch(email_params)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to send rejection cancellation emails: %s", e)
    return RedirectResponse(url=f"/requisitions/{req_id}?success=Requisition+rejected", status_code=303)






