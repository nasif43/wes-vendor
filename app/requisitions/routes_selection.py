"""
Requisition vendor selection and negotiation routes.

Handles:
- Vendor invitation (v1 links)
- Temporary vendor creation
- Shortlisting (per-vendor, will be extended to per-item in Phase 3)
- Negotiation round initiation (v2 links)

NAMING: 'vendor' = ORM/DB internal. 'supplier' = UI label in templates.
"""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile, UserRole
from app.categories.models import Category
from app.database import get_db
from app.dependencies import get_current_user
from app.email.resend import build_vendor_invitation, build_negotiation_invitation, build_rejection_notification, send_batch
from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor, ShortlistedItem
from app.vendors.models import Vendor

logger = logging.getLogger(__name__)
router = APIRouter()

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
        await db.commit()
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
        await db.commit()
        return RedirectResponse(url="/requisitions", status_code=303)

    if user.role not in [UserRole.PROCUREMENT, UserRole.ADMIN] and req.created_by != user.id:
        await db.commit()
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

    # Check for existing links to prevent sending multiple RFQs to the same supplier (v1)
    existing_links_res = await db.execute(
        select(RequisitionVendor.vendor_id).where(
            RequisitionVendor.requisition_id == req_id,
            RequisitionVendor.vendor_id.in_(vendor_ids)
        )
    )
    existing_vendor_ids = set(existing_links_res.scalars().all())

    links = []
    for vendor_id in vendor_ids:
        if vendor_id in existing_vendor_ids:
            continue  # Skip if this vendor was already invited to this requisition
            
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
            from app.reports.pdf_service import generate_rfq_pdf
            import os
            from app.config import get_settings
            
            pdf_bytes = generate_rfq_pdf(req, vendor.company_name, req.items or [])
            if pdf_bytes:
                settings = get_settings()
                rfq_dir = os.path.join(settings.upload_dir, "rfqs")
                os.makedirs(rfq_dir, exist_ok=True)
                pdf_path = os.path.join(rfq_dir, f"RFQ_{req.id}_{vendor.id}_v1.pdf")
                with open(pdf_path, "wb") as f:
                    f.write(pdf_bytes)

            email_params.append(
                await build_vendor_invitation(
                    to=vendor.contact_email,
                    vendor_name=vendor.contact_person or vendor.company_name,
                    requisition_title=req.title,
                    quote_url=quote_url,
                    pdf_bytes=pdf_bytes,
                )
            )

    email_sent = True
    if email_params:
        email_sent = await send_batch(email_params)

    if req.status == RequisitionStatus.DRAFT:
        from app.requisitions.service import transition_requisition_status
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=RequisitionStatus.NEW,
            actor=user,
            action_name="VENDORS_INVITED",
            notes=f"{len(vendor_ids)} vendor(s) invited via quote link",
        )

    if not email_sent:
        await db.commit()
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Links+created+but+email+failed.+Share+links+manually.",
            status_code=303,
        )
    await db.commit()
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
        company_name="Temporary Supplier",
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
        entity_label=f"Unlisted Supplier ({req.title})",
        notes=f"Unlisted/Temporary supplier link created for Requisition #{req_id} by {user.full_name} ({user.email}).",
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

    await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}?success=Temporary+supplier+link+generated", status_code=303)

@router.post("/{req_id}/shortlist")
async def shortlist_vendors(
    req_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Shortlist suppliers with optional per-item selection.
    
    Form data format:
      shortlisted_ids[]   = list of RequisitionVendor IDs to shortlist
      items_{link_id}[]   = list of item indices (0-based) shortlisted for that supplier
      qty_{link_id}_{idx} = allocated quantity for that supplier+item combo
    """
    from app.auth.models import UserRole
    from app.requisitions.models import ShortlistedItem
    from sqlalchemy import delete
    
    if not (user.has_management_authority or user.role == UserRole.ADMIN):
        return RedirectResponse(
            url=f"/quotations/compare/{req_id}?error=Permission+denied",
            status_code=303,
        )

    form_data = await request.form()
    shortlisted_ids: list[str] = list(form_data.getlist("shortlisted_ids"))

    # Reset all existing shortlisting for this requisition
    all_links_res = await db.execute(
        select(RequisitionVendor).where(RequisitionVendor.requisition_id == req_id)
    )
    all_links = all_links_res.scalars().all()
    for lnk in all_links:
        lnk.is_shortlisted = False
        lnk.allocated_quantity = None

    # Delete existing ShortlistedItem rows for this requisition's vendor links
    link_ids = [lnk.id for lnk in all_links]
    if link_ids:
        await db.execute(
            delete(ShortlistedItem).where(
                ShortlistedItem.requisition_vendor_id.in_(link_ids)
            )
        )

    # Process each shortlisted link
    for link_id in shortlisted_ids:
        res = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.id == link_id,
                RequisitionVendor.requisition_id == req_id,
            )
        )
        lnk = res.scalar_one_or_none()
        if not lnk:
            continue

        lnk.is_shortlisted = True

        # Check for per-item selections
        item_indices = form_data.getlist(f"items_{link_id}")
        if item_indices:
            # Per-item shortlisting mode
            total_qty = 0.0
            for idx_str in item_indices:
                try:
                    idx = int(idx_str)
                except ValueError:
                    continue
                qty_str = form_data.get(f"qty_{link_id}_{idx}", "")
                try:
                    qty = float(qty_str) if qty_str else 0.0
                except (ValueError, TypeError):
                    qty = 0.0
                total_qty += qty

                # Get item name from requisition
                item_name = f"Item {idx + 1}"
                if lnk.requisition and lnk.requisition.items:
                    items_list = lnk.requisition.items
                    if idx < len(items_list):
                        item_name = items_list[idx].get("name", item_name)

                si = ShortlistedItem(
                    requisition_vendor_id=link_id,
                    item_index=idx,
                    item_name=item_name,
                    shortlisted_qty=qty,
                )
                db.add(si)
            lnk.allocated_quantity = total_qty if total_qty > 0 else None
        else:
            # Fallback: whole-vendor shortlisting (no per-item breakdown)
            qty_str = form_data.get(f"alloc_qty_{link_id}", "")
            try:
                lnk.allocated_quantity = float(qty_str) if qty_str else None
            except (ValueError, TypeError):
                lnk.allocated_quantity = None

    await log_action(
        db,
        actor=user,
        action="VENDORS_SHORTLISTED",
        entity_type="requisition",
        entity_id=req_id,
        entity_label=f"Requisition #{req_id}",
        notes=f"{len(shortlisted_ids)} supplier(s) shortlisted by {user.full_name}",
    )
    await db.flush()
    await db.commit()
    return RedirectResponse(
        url=f"/quotations/compare/{req_id}?success=Suppliers+shortlisted",
        status_code=303,
    )


@router.post("/{req_id}/negotiate")
async def start_negotiation(
    req_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate v2 quote links for all shortlisted vendors in this requisition."""
    from app.auth.models import UserRole
    from datetime import UTC, datetime

    if not (user.has_management_authority or user.is_procurement or user.role == UserRole.ADMIN):
        return RedirectResponse(url=f"/quotations/compare/{req_id}?error=Permission+denied", status_code=303)

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        return RedirectResponse(url="/requisitions", status_code=303)

    # Find shortlisted vendor links (v1 only, not already v2)
    shortlisted_res = await db.execute(
        select(RequisitionVendor)
        .options(selectinload(RequisitionVendor.shortlisted_items))
        .where(
            RequisitionVendor.requisition_id == req_id,
            RequisitionVendor.is_shortlisted == True,
            RequisitionVendor.negotiation_version == 1,
        )
    )
    shortlisted = shortlisted_res.scalars().all()
    if not shortlisted:
        return RedirectResponse(
        url=f"/quotations/compare/{req_id}?error=No+shortlisted+suppliers+found.+Shortlist+suppliers+first.",
        status_code=303,
        )

    v2_links = []
    for lnk in shortlisted:
        # Check if a v2 link already exists for this vendor in this req
        existing_v2_res = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.requisition_id == req_id,
                RequisitionVendor.vendor_id == lnk.vendor_id,
                RequisitionVendor.negotiation_version == 2,
            )
        )
        existing_v2 = existing_v2_res.scalar_one_or_none()
        if existing_v2:
            v2_links.append(existing_v2)
            continue

        v2_link = RequisitionVendor(
            requisition_id=req_id,
            vendor_id=lnk.vendor_id,
            status="pending",
            is_shortlisted=True,
            allocated_quantity=lnk.allocated_quantity,
            negotiation_version=2,
            link_sent_at=datetime.now(UTC),
        )
        db.add(v2_link)
        await db.flush()  # Need ID for ShortlistedItems
        
        # Copy shortlisted items from v1 link to v2 link
        from app.requisitions.models import ShortlistedItem
        for s_item in lnk.shortlisted_items:
            db.add(
                ShortlistedItem(
                    requisition_vendor_id=v2_link.id,
                    item_index=s_item.item_index,
                    item_name=s_item.item_name,
                    shortlisted_qty=s_item.shortlisted_qty,
                )
            )
            
        v2_links.append(v2_link)

    await db.flush()

    # Send v2 invitation emails
    try:
        email_params = []
        for v2_lnk in v2_links:
            vendor = v2_lnk.vendor
            if vendor and vendor.contact_email:
                quote_url = f"{str(request.base_url).rstrip('/')}/vendor-quote/{v2_lnk.unique_link_token}"
                
                # Build items specifically for this supplier's v2 negotiation
                shortlisted = []
                from app.requisitions.models import ShortlistedItem
                from sqlalchemy import select
                s_res = await db.execute(select(ShortlistedItem).where(ShortlistedItem.requisition_vendor_id == v2_lnk.id))
                s_items = s_res.scalars().all()
                for s_item in s_items:
                    # Find original description if available
                    desc = ""
                    if req.items:
                        try:
                            desc = req.items[s_item.item_index].get("description", "")
                        except (IndexError, TypeError):
                            pass
                    shortlisted.append({
                        "name": s_item.item_name,
                        "description": desc,
                        "shortlisted_qty": s_item.shortlisted_qty
                    })
                
                from app.reports.pdf_service import generate_rfq_pdf
                import os
                from app.config import get_settings
                
                pdf_bytes = generate_rfq_pdf(req, vendor.company_name, shortlisted)
                if pdf_bytes:
                    settings = get_settings()
                    rfq_dir = os.path.join(settings.upload_dir, "rfqs")
                    os.makedirs(rfq_dir, exist_ok=True)
                    pdf_path = os.path.join(rfq_dir, f"RFQ_{req.id}_{vendor.id}_v2.pdf")
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)

                
                email_params.append(
                    await build_negotiation_invitation(
                        to=vendor.contact_email,
                        supplier_name=vendor.contact_person or vendor.company_name,
                        requisition_title=req.title,
                        quote_url=quote_url,
                        pdf_bytes=pdf_bytes,
                    )
                )
        if email_params:
            await send_batch(email_params)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).exception("Failed to send v2 negotiation emails: %s", e)

    # Transition to NEGOTIATING status
    from app.requisitions.service import transition_requisition_status, InvalidStateTransitionError
    from app.requisitions.models import RequisitionStatus
    import logging
    logger = logging.getLogger(__name__)
    try:
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=RequisitionStatus.NEGOTIATING,
            actor=user,
            action_name="NEGOTIATION_STARTED",
            notes=f"v2 links generated for {len(v2_links)} supplier(s). Non-shortlisted suppliers will be notified.",
        )
    except InvalidStateTransitionError as e:
        logger.warning("Could not transition to NEGOTIATING: %s", e)

    # Send rejection notifications to non-shortlisted v1 vendors
    try:
        from app.email.resend import send_batch
        non_shortlisted_res = await db.execute(
            select(RequisitionVendor).where(
                RequisitionVendor.requisition_id == req_id,
                RequisitionVendor.is_shortlisted == False,
                RequisitionVendor.negotiation_version == 1,
                RequisitionVendor.status == "submitted",
            )
        )
        non_shortlisted = non_shortlisted_res.scalars().all()
        rejection_params = []
        for lnk in non_shortlisted:
            vendor = lnk.vendor
            if vendor and vendor.contact_email:
                param = await build_rejection_notification(
                    to=vendor.contact_email,
                    supplier_name=vendor.contact_person or vendor.company_name,
                    requisition_title=req.title,
                )
                if param:
                    rejection_params.append(param)
        if rejection_params:
            await send_batch(rejection_params)
    except Exception as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning("Failed to send rejection emails: %s", _e)

    await log_action(
        db,
        actor=user,
        action="NEGOTIATION_STARTED",
        entity_type="requisition",
        entity_id=req_id,
        entity_label=req.title,
        notes=f"v2 negotiation links generated for {len(v2_links)} vendor(s) by {user.full_name}",
    )
    await db.flush()
    await db.commit()
    return RedirectResponse(
        url=f"/quotations/compare/{req_id}?success=Negotiation+links+sent", status_code=303
    )



@router.post("/{req_id}/resend-link/{link_id}")
async def resend_supplier_link(
    request: Request,
    req_id: str,
    link_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.auth.models import UserRole
    if not (user.is_procurement or user.has_management_authority or user.role == UserRole.ADMIN):
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    result = await db.execute(
        select(RequisitionVendor)
        .options(
            selectinload(RequisitionVendor.vendor),
            selectinload(RequisitionVendor.requisition),
            selectinload(RequisitionVendor.shortlisted_items),
        )
        .where(RequisitionVendor.id == link_id)
    )
    link = result.scalar_one_or_none()
    
    if not link or link.requisition_id != req_id:
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Link+not+found", status_code=303)
        
    if link.status == 'submitted':
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Supplier+already+submitted", status_code=303)
        
    vendor = link.vendor
    req = link.requisition
    
    if not vendor or not vendor.contact_email:
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Supplier+has+no+email", status_code=303)

    quote_url = f"{str(request.base_url).rstrip('/')}/vendor-quote/{link.unique_link_token}"
    email_params = []
    
    from app.reports.pdf_service import generate_rfq_pdf
    from app.email.resend import send_batch, build_vendor_invitation, build_negotiation_invitation
    
    if link.negotiation_version == 2:
        # Re-build shortlisted items
        shortlisted = []
        for s_item in link.shortlisted_items:
            desc = ""
            if req.items and s_item.item_index < len(req.items):
                desc = req.items[s_item.item_index].get("description", "")
            shortlisted.append({
                "name": s_item.item_name,
                "description": desc,
                "shortlisted_qty": s_item.shortlisted_qty
            })
        pdf_bytes = generate_rfq_pdf(req, vendor.company_name, shortlisted)
        email_params.append(
            await build_negotiation_invitation(
                to=vendor.contact_email,
                supplier_name=vendor.contact_person or vendor.company_name,
                requisition_title=req.title,
                quote_url=quote_url,
                pdf_bytes=pdf_bytes,
            )
        )
    else:
        pdf_bytes = generate_rfq_pdf(req, vendor.company_name, req.items or [])
        email_params.append(
            await build_vendor_invitation(
                to=vendor.contact_email,
                vendor_name=vendor.contact_person or vendor.company_name,
                requisition_title=req.title,
                quote_url=quote_url,
                pdf_bytes=pdf_bytes,
            )
        )

    if email_params:
        try:
            await send_batch(email_params)
            from datetime import datetime, UTC
            link.link_sent_at = datetime.now(UTC)
            await db.commit()
            return RedirectResponse(url=f"/requisitions/{req_id}?success=Email+sent+to+{vendor.company_name}", status_code=303)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to resend email: %s", e)
            return RedirectResponse(url=f"/requisitions/{req_id}?error=Failed+to+send+email", status_code=303)
            
    return RedirectResponse(url=f"/requisitions/{req_id}", status_code=303)
