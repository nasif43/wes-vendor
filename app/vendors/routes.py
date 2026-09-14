from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.models import UserProfile
from app.categories.models import Category
from app.database import get_db
from app.dependencies import get_current_user
from app.vendors.models import Vendor, vendor_categories

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_vendors(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(
        select(Vendor).where(Vendor.is_active == True, Vendor.is_temporary == False).order_by(Vendor.company_name)
    )
    vendors = result.scalars().all()
    return templates.TemplateResponse(
        request, "vendors/list.html", {"user": user, "vendors": vendors}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_vendor_page(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Category).order_by(Category.name))
    categories = result.scalars().all()
    return templates.TemplateResponse(
        request, "vendors/create.html", {"user": user, "categories": categories}
    )


@router.post("")
async def create_vendor(
    request: Request,
    company_name: str = Form(...),
    contact_email: str = Form(...),
    contact_person: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    category_ids: list[str] = Form([]),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    vendor = Vendor(
        company_name=company_name,
        contact_email=contact_email,
        contact_person=contact_person or None,
        phone=phone or None,
        notes=notes or None,
        created_by=user.id,
    )
    db.add(vendor)
    await db.flush()

    if category_ids:
        for cat_id in category_ids:
            await db.execute(
                vendor_categories.insert().values(vendor_id=vendor.id, category_id=cat_id)
            )

    # ── Audit log ──────────────────────────────────────────────────────────────
    await log_action(
        db,
        actor=user,
        action="VENDOR_CREATED",
        entity_type="vendor",
        entity_id=vendor.id,
        entity_label=vendor.company_name,
        notes=f"Email: {vendor.contact_email}. Created by {user.full_name} ({user.email}).",
    )

    await db.commit()
    return RedirectResponse(url="/vendors?success=1", status_code=303)


@router.get("/{vendor_id}", response_class=HTMLResponse)
async def view_vendor(
    request: Request,
    vendor_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        return RedirectResponse(url="/vendors", status_code=303)

    result = await db.execute(select(Category).order_by(Category.name))
    categories = result.scalars().all()
    
    # Fetch supplier performance ratings
    supplier_ratings = []
    try:
        from app.work_orders.models import SupplierRating
        ratings_res = await db.execute(
            select(SupplierRating)
            .where(SupplierRating.vendor_id == vendor_id)
            .order_by(SupplierRating.rated_at.desc())
        )
        supplier_ratings = ratings_res.scalars().all()
    except Exception:
        pass
    
    # Compute aggregate stats
    perf_stats = {}
    if supplier_ratings:
        delivery_times = [float(r.delivery_days) for r in supplier_ratings if r.delivery_days]
        defect_rates = [float(r.defect_rate_pct) for r in supplier_ratings]
        total_ordered = sum(float(r.ordered_qty) for r in supplier_ratings)
        total_received = sum(float(r.received_qty) for r in supplier_ratings)
        total_rejected = sum(float(r.rejected_qty) for r in supplier_ratings)
        perf_stats = {
            "total_orders": len(supplier_ratings),
            "avg_delivery_days": round(sum(delivery_times) / len(delivery_times), 1) if delivery_times else None,
            "avg_defect_rate": round(sum(defect_rates) / len(defect_rates), 1) if defect_rates else 0.0,
            "total_ordered": total_ordered,
            "total_received": total_received,
            "total_rejected": total_rejected,
        }

    return templates.TemplateResponse(
        request, "vendors/detail.html",
        {"user": user, "vendor": vendor, "categories": categories,
         "supplier_ratings": supplier_ratings, "perf_stats": perf_stats}
    )


@router.post("/{vendor_id}")
async def update_vendor(
    request: Request,
    vendor_id: str,
    company_name: str = Form(...),
    contact_email: str = Form(...),
    contact_person: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("true"),
    category_ids: list[str] = Form([]),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        return RedirectResponse(url="/vendors", status_code=303)

    vendor.company_name = company_name
    vendor.contact_email = contact_email
    vendor.contact_person = contact_person or None
    vendor.phone = phone or None
    vendor.notes = notes or None
    vendor.is_active = is_active == "true"

    await db.execute(
        vendor_categories.delete().where(vendor_categories.c.vendor_id == vendor_id)
    )
    if category_ids:
        for cat_id in category_ids:
            await db.execute(
                vendor_categories.insert().values(vendor_id=vendor_id, category_id=cat_id)
            )

    # ── Audit log ──────────────────────────────────────────────────────────────
    await log_action(
        db,
        actor=user,
        action="VENDOR_UPDATED",
        entity_type="vendor",
        entity_id=vendor.id,
        entity_label=vendor.company_name,
        notes=f"Updated by {user.full_name} ({user.email}). Active: {vendor.is_active}.",
    )

    await db.commit()
    return RedirectResponse(url=f"/vendors/{vendor_id}?success=1", status_code=303)


@router.post("/{vendor_id}/delete")
async def delete_vendor(
    vendor_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor:
        await log_action(
            db,
            actor=user,
            action="VENDOR_DELETED",
            entity_type="vendor",
            entity_id=vendor_id,
            entity_label=vendor.company_name,
            notes=f"Deleted by {user.full_name} ({user.email}).",
        )
        await db.delete(vendor)
    await db.commit()
    return RedirectResponse(url="/vendors?success=1", status_code=303)


@router.get("/{vendor_id}/audit", response_class=HTMLResponse)
async def vendor_audit_notes(
    request: Request,
    vendor_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Show audit/rejection notes for a specific vendor — management/admin only."""
    from app.main import templates
    from app.audit.models import AuditLog

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        return RedirectResponse(url="/vendors", status_code=303)

    # Fetch rejection and QC_FAILED events related to this vendor
    audit_res = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.notes.contains(vendor.company_name)
            | (AuditLog.entity_id == vendor_id)
        )
        .order_by(AuditLog.created_at.desc())
        .limit(50)
    )
    audit_logs = audit_res.scalars().all()

    return templates.TemplateResponse(
        request,
        "vendors/audit.html",
        {"user": user, "vendor": vendor, "audit_logs": audit_logs},
    )


@router.post("/{vendor_id}/reject-note")
async def add_vendor_rejection_note(
    request: Request,
    vendor_id: str,
    note_text: str = Form(...),
    qc_failed: bool = Form(False),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Log a rejection or QC failure note against a vendor profile."""
    from app.main import templates  # noqa: F401
    from app.auth.models import UserRole

    if not (user.has_management_authority or user.role == UserRole.ADMIN):
        return RedirectResponse(url=f"/vendors/{vendor_id}?error=Permission+denied", status_code=303)

    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        return RedirectResponse(url="/vendors", status_code=303)

    action = "QC_FAILED" if qc_failed else "VENDOR_REJECTED"
    await log_action(
        db,
        actor=user,
        action=action,
        entity_type="vendor",
        entity_id=vendor_id,
        entity_label=vendor.company_name,
        notes=note_text,
    )
    await db.flush()
    await db.commit()
    return RedirectResponse(
        url=f"/vendors/{vendor_id}/audit?success=Note+added", status_code=303
    )
