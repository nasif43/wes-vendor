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

    if not (user.can_see_all_requisitions or req.created_by == user.id):
        await db.commit()
        return RedirectResponse(url="/requisitions?error=Permission+denied", status_code=303)

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

    if not (user.can_see_all_requisitions or req.created_by == user.id):
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
            status="pending",
        )
        db.add(link)
        links.append(link)

    await db.flush()

    email_params = []
    emailed_links = []
    for link in links:
        vendor = vendors_map.get(link.vendor_id)
        if vendor and vendor.contact_email:
            quote_url = f"{str(request.base_url).rstrip('/')}/vendor-quote/{link.unique_link_token}"
            from app.reports.pdf_service import generate_rfq_pdf
            import os
            from app.config import get_settings
            
            pdf_bytes = generate_rfq_pdf(
                req, vendor.company_name, req.items or [],
                issuer_name=user.full_name or user.username,
                issued_at=datetime.now(UTC),
            )
            if pdf_bytes:
                settings = get_settings()
                rfq_dir = os.path.join(settings.upload_dir, "rfqs")
                os.makedirs(rfq_dir, exist_ok=True)
                pdf_path = os.path.join(rfq_dir, f"RFQ_{req.id}_{vendor.id}_v1.pdf")
                with open(pdf_path, "wb") as f:
                    f.write(pdf_bytes)

            req_ref = req.reference_code if hasattr(req, "reference_code") else f"REQ-{req.id[:8].upper()}"
            email_params.append(
                await build_vendor_invitation(
                    to=vendor.contact_email,
                    vendor_name=vendor.contact_person or vendor.company_name,
                    requisition_title=req.title,
                    quote_url=quote_url,
                    pdf_bytes=pdf_bytes,
                    company_name=vendor.company_name,
                    contact_person=vendor.contact_person,
                    requisition_ref=req_ref,
                )
            )
            emailed_links.append(link)

    # Links without a supplier email were created but could not be delivered.
    email_sent = not links
    if email_params:
        email_sent = await send_batch(email_params)
        if email_sent:
            sent_at = datetime.now(UTC)
            for emailed_link in emailed_links:
                emailed_link.link_sent_at = sent_at

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

    if not (user.can_see_all_requisitions or req.created_by == user.id):
        await db.commit()
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

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
    negotiation_email_sent = False
    try:
        email_params = []
        email_links = []
        for v2_lnk in v2_links:
            vendor = v2_lnk.vendor
            if vendor and vendor.contact_email:
                quote_url = f"{str(request.base_url).rstrip('/')}/vendor-quote/{v2_lnk.unique_link_token}"
                
                # Build items specifically for this supplier's v2 negotiation
                shortlisted = []
                from app.requisitions.models import ShortlistedItem
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
                
                pdf_bytes = generate_rfq_pdf(
                    req, vendor.company_name, shortlisted,
                    issuer_name=user.full_name or user.username,
                    issued_at=datetime.now(UTC),
                )
                if pdf_bytes:
                    settings = get_settings()
                    rfq_dir = os.path.join(settings.upload_dir, "rfqs")
                    os.makedirs(rfq_dir, exist_ok=True)
                    pdf_path = os.path.join(rfq_dir, f"RFQ_{req.id}_{vendor.id}_v2.pdf")
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)

                
                req_ref = req.reference_code if hasattr(req, "reference_code") else f"REQ-{req.id[:8].upper()}"
                email_params.append(
                    await build_negotiation_invitation(
                        to=vendor.contact_email,
                        supplier_name=vendor.contact_person or vendor.company_name,
                        requisition_title=req.title,
                        quote_url=quote_url,
                        pdf_bytes=pdf_bytes,
                        company_name=vendor.company_name,
                        contact_person=vendor.contact_person,
                        requisition_ref=req_ref,
                    )
                )
                email_links.append(v2_lnk)
        if email_params:
            negotiation_email_sent = await send_batch(email_params)
            if negotiation_email_sent:
                sent_at = datetime.now(UTC)
                for emailed_link in email_links:
                    emailed_link.link_sent_at = sent_at
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).exception("Failed to send v2 negotiation emails: %s", e)

    # Transition to NEGOTIATING status
    from app.requisitions.service import transition_requisition_status, InvalidStateTransitionError
    from app.requisitions.models import RequisitionStatus
    import logging
    logger = logging.getLogger(__name__)

    contacted_supplier_names = [
        v2_lnk.vendor.company_name for v2_lnk in v2_links if v2_lnk.vendor and v2_lnk.vendor.company_name
    ]

    try:
        await transition_requisition_status(
            db,
            requisition=req,
            target_status=RequisitionStatus.NEGOTIATING,
            actor=user,
            action_name="NEGOTIATION_STARTED",
            notes=f"v2 negotiation links generated for {len(v2_links)} supplier(s): {', '.join(contacted_supplier_names)}.",
        )
    except InvalidStateTransitionError as e:
        logger.warning("Could not transition to NEGOTIATING: %s", e)

    # Notify the procurement officer responsible for this requisition
    creator = req.creator
    if creator and creator.email:
        try:
            from app.email.resend import build_negotiation_procurement_notification
            base_url = str(request.base_url).rstrip("/")
            req_url = f"{base_url}/requisitions/{req.id}"
            proc_param = await build_negotiation_procurement_notification(
                to=creator.email,
                procurement_officer_name=creator.full_name or creator.username,
                requisition_title=req.title,
                requisition_ref=req.reference_code,
                contacted_suppliers=contacted_supplier_names,
                requisition_url=req_url,
            )
            if proc_param:
                await send_batch([proc_param])
        except Exception as _e:
            logger.warning("Failed to notify procurement officer of negotiation: %s", _e)

    await log_action(
        db,
        actor=user,
        action="NEGOTIATION_STARTED",
        entity_type="requisition",
        entity_id=req_id,
        entity_label=f"Requisition #{req_id}",
        notes=f"v2 negotiation started for {len(v2_links)} supplier(s): {', '.join(contacted_supplier_names)}. Procurement officer ({creator.full_name if creator else 'Procurement'}) notified.",
    )
    await db.flush()
    await db.commit()
    if not negotiation_email_sent:
        return RedirectResponse(
            url=(
                f"/quotations/compare/{req_id}?error="
                "Negotiation+links+created,+but+email+delivery+failed"
            ),
            status_code=303,
        )
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

    if not (user.can_see_all_requisitions or link.requisition.created_by == user.id):
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)
        
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
    
    if link.shortlisted_items:
        # Re-build shortlisted items
        shortlisted = []
        for s_item in link.shortlisted_items:
            desc = ""
            if req.items and s_item.item_index < len(req.items):
                desc = req.items[s_item.item_index].get("description", "")
            shortlisted.append({
                "name": s_item.item_name,
                "description": desc,
                "shortlisted_qty": s_item.shortlisted_qty,
                "qty": s_item.shortlisted_qty,
            })
        pdf_bytes = generate_rfq_pdf(
            req, vendor.company_name, shortlisted,
            issuer_name=user.full_name or user.username,
            issued_at=datetime.now(UTC),
        )
        req_ref = req.reference_code if hasattr(req, "reference_code") else f"REQ-{req.id[:8].upper()}"
        if link.negotiation_version == 2:
            email_params.append(
                await build_negotiation_invitation(
                    to=vendor.contact_email,
                    supplier_name=vendor.contact_person or vendor.company_name,
                    requisition_title=req.title,
                    quote_url=quote_url,
                    pdf_bytes=pdf_bytes,
                    company_name=vendor.company_name,
                    contact_person=vendor.contact_person,
                    requisition_ref=req_ref,
                )
            )
        else:
            email_params.append(
                await build_vendor_invitation(
                    to=vendor.contact_email,
                    vendor_name=vendor.contact_person or vendor.company_name,
                    requisition_title=req.title,
                    quote_url=quote_url,
                    pdf_bytes=pdf_bytes,
                    company_name=vendor.company_name,
                    contact_person=vendor.contact_person,
                    requisition_ref=req_ref,
                )
            )
    else:
        pdf_bytes = generate_rfq_pdf(
            req, vendor.company_name, req.items or [],
            issuer_name=user.full_name or user.username,
            issued_at=datetime.now(UTC),
        )
        req_ref = req.reference_code if hasattr(req, "reference_code") else f"REQ-{req.id[:8].upper()}"
        email_params.append(
            await build_vendor_invitation(
                to=vendor.contact_email,
                vendor_name=vendor.contact_person or vendor.company_name,
                requisition_title=req.title,
                quote_url=quote_url,
                pdf_bytes=pdf_bytes,
                company_name=vendor.company_name,
                contact_person=vendor.contact_person,
                requisition_ref=req_ref,
            )
        )

    if email_params:
        try:
            email_sent = await send_batch(email_params)
            if not email_sent:
                return RedirectResponse(
                    url=f"/requisitions/{req_id}?error=Failed+to+send+email",
                    status_code=303,
                )
            link.link_sent_at = datetime.now(UTC)
            await db.commit()
            return RedirectResponse(url=f"/requisitions/{req_id}?success=Email+sent+to+{vendor.company_name}", status_code=303)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to resend email: %s", e)
            return RedirectResponse(url=f"/requisitions/{req_id}?error=Failed+to+send+email", status_code=303)
            
    return RedirectResponse(url=f"/requisitions/{req_id}", status_code=303)


@router.post("/{req_id}/forward-quotes-cc")
async def forward_all_quotes_to_cc(
    req_id: str,
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
        return RedirectResponse(url=f"/requisitions/{req_id}?error=Permission+denied", status_code=303)

    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        await db.commit()
        return RedirectResponse(url="/requisitions?error=Requisition+not+found", status_code=303)

    cc = await get_cc_emails()
    if not cc:
        await db.commit()
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=No+CC+recipients+configured.+Add+management+emails+in+Settings+first.",
            status_code=303,
        )

    links_res = await db.execute(
        select(RequisitionVendor)
        .options(
            selectinload(RequisitionVendor.vendor),
            selectinload(RequisitionVendor.quotations),
        )
        .where(RequisitionVendor.requisition_id == req_id)
    )
    links = links_res.scalars().all()
    submitted_links = [
        l for l in links
        if l.status == "submitted" or l.quotation is not None
    ]

    if not submitted_links:
        await db.commit()
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=No+submitted+quotations+found+to+forward.",
            status_code=303,
        )

    attachments = []
    table_rows = []
    forwarded_vendors = []
    compare_url = f"{str(request.base_url).rstrip('/')}/quotations/compare/{req_id}"

    from app.utils.number_formatting import format_indian_number

    for link in submitted_links:
        form_data = link.quotation.form_data if (link.quotation and link.quotation.form_data) else {}
        vendor_name = link.vendor.company_name if link.vendor else "Supplier"
        view_url = f"{str(request.base_url).rstrip('/')}/quotations/detail/{link.id}"

        pdf_bytes = _generate_quotation_pdf(
            form_data,
            req_title=req.title,
            vendor_name=vendor_name,
        )
        if pdf_bytes:
            attachments.append({
                "filename": f"Quotation_{vendor_name.replace(' ', '_')}.pdf",
                "content": list(pdf_bytes),
                "content_type": "application/pdf"
            })

        # Calculate price display
        raw_price = form_data.get("price")
        price_display = "—"
        if raw_price is not None:
            try:
                price_display = f"৳{format_indian_number(float(raw_price))}"
            except Exception:
                price_display = f"৳{raw_price}"

        delivery = form_data.get("delivery_days", "—")
        contact_str = f"{link.vendor.contact_person or '—'} ({link.vendor.contact_email or '—'})" if link.vendor else "—"

        table_rows.append(f"""
        <tr style="border-bottom:1px solid #e2e8f0;">
          <td style="padding:10px 12px; font-weight:bold; color:#0f172a;">{vendor_name}</td>
          <td style="padding:10px 12px; color:#475569; font-size:12px;">{contact_str}</td>
          <td style="padding:10px 12px; text-align:right; font-weight:bold; color:#0f172a; font-family:monospace;">{price_display}</td>
          <td style="padding:10px 12px; text-align:center; color:#334155;">{delivery} days</td>
          <td style="padding:10px 12px; text-align:center;"><span style="background:#fef3c7; color:#92400e; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:bold;">v{link.negotiation_version}</span></td>
          <td style="padding:10px 12px; text-align:center;"><a href="{view_url}" style="color:#2563eb; font-size:12px; font-weight:600; text-decoration:none;">View Detail &rarr;</a></td>
        </tr>
        """)
        forwarded_vendors.append(vendor_name)

    from app.email.resend import _email_footer
    footer = _email_footer()
    req_ref = req.reference_code if hasattr(req, "reference_code") else f"REQ-{req.id[:8].upper()}"

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; color:#1e293b; max-width:680px; line-height:1.5;">
      <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 18px; margin-bottom:20px;">
        <span style="font-size:11px; font-weight:bold; color:#64748b; text-transform:uppercase; letter-spacing:0.05em;">Requisition Grouped Quotations Summary</span>
        <h2 style="margin:4px 0 6px 0; font-size:18px; color:#0f172a;">[{req_ref}] {req.title}</h2>
        <p style="margin:0; font-size:13px; color:#475569;">
          <strong>Total Submitted Quotes:</strong> {len(submitted_links)} &nbsp;|&nbsp;
          <strong>Forwarded By:</strong> {user.full_name} ({user.email})
        </p>
      </div>

      <p style="font-size:14px; margin-bottom:12px;">Here is the executive summary of all submitted supplier quotations for this requisition:</p>

      <table style="width:100%; border-collapse:collapse; font-size:13px; margin:16px 0; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;">
        <thead>
          <tr style="background:#f1f5f9; text-align:left; border-bottom:2px solid #cbd5e1; font-size:11px; text-transform:uppercase; color:#64748b; letter-spacing:0.05em;">
            <th style="padding:10px 12px;">Supplier</th>
            <th style="padding:10px 12px;">Contact</th>
            <th style="padding:10px 12px; text-align:right;">Offered Total</th>
            <th style="padding:10px 12px; text-align:center;">Delivery</th>
            <th style="padding:10px 12px; text-align:center;">Round</th>
            <th style="padding:10px 12px; text-align:center;">Action</th>
          </tr>
        </thead>
        <tbody>
          {"".join(table_rows)}
        </tbody>
      </table>

      <div style="margin:24px 0;">
        <a href="{compare_url}" style="display:inline-block; background:#1d4ed8; color:#ffffff; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:700; font-size:14px; box-shadow:0 1px 3px rgba(0,0,0,0.1);">
          📊 Open Side-by-Side Comparison Matrix in Portal
        </a>
      </div>

      <p style="font-size:12px; color:#64748b; margin-top:20px; border-top:1px solid #e2e8f0; padding-top:12px;">
        📎 <strong>Attachments:</strong> All {len(attachments)} quotation summary PDF document(s) are attached to this email.
      </p>

      {footer}
    </div>
    """

    payload = {
        "from": f"Wener Supplier Management <{email_settings.mail_from}>",
        "to": cc,
        "subject": f"[{req_ref}] Quotations Summary: {req.title} ({len(submitted_links)} Quotes Submitted)",
        "html": html,
    }
    if attachments:
        payload["attachments"] = attachments

    sent = await send_batch([payload])
    if not sent:
        await db.commit()
        return RedirectResponse(
            url=f"/requisitions/{req_id}?error=Failed+to+forward+email+via+Resend.+Check+Resend+API+key+or+quota.",
            status_code=303,
        )

    await log_action(
        db,
        actor=user,
        action="QUOTATIONS_BATCH_FORWARDED_TO_CC",
        entity_type="requisition",
        entity_id=req.id,
        entity_label=req.title,
        notes=f"Forwarded consolidated quotations summary email with {len(attachments)} PDFs ({', '.join(forwarded_vendors)}) to CCs: {', '.join(cc)} by {user.full_name}.",
    )
    await db.flush()
    await db.commit()

    return RedirectResponse(
        url=f"/requisitions/{req_id}?success=Forwarded+consolidated+quotations+summary+and+{len(attachments)}+PDFs+to+management+CCs",
        status_code=303,
    )

