import logging
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit.service import log_action
from app.auth.models import UserProfile, UserRole
from app.categories.models import Category
from app.database import get_db
from app.dependencies import get_current_user
from app.storage import upload_file
from app.vendors.models import Vendor
from app.cash_purchases.models import CashPurchase

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}


def get_dhaka_today() -> date:
    try:
        return datetime.now(ZoneInfo("Asia/Dhaka")).date()
    except Exception:
        return datetime.now().date()


def generate_reference_number(purchase_date: date) -> str:
    compact_date = purchase_date.strftime("%Y%m%d")
    unique_suffix = uuid.uuid4().hex[:6].upper()
    return f"CP-{compact_date}-{unique_suffix}"


@router.get("", response_class=HTMLResponse)
async def list_cash_purchases(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    amount_min: str = "",
    amount_max: str = "",
    vendor_id: str = "",
    created_by: str = "",
    sort: str = "purchase_date_desc",
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    stmt = select(CashPurchase).options(
        selectinload(CashPurchase.creator),
        selectinload(CashPurchase.vendor),
        selectinload(CashPurchase.category),
    )

    # ── Role-based Visibility ────────────────────────────────────────────────
    if not user.can_see_all_requisitions:
        stmt = stmt.where(CashPurchase.created_by == user.id)
    elif created_by:
        stmt = stmt.where(CashPurchase.created_by == created_by)

    # ── Search Filter ────────────────────────────────────────────────────────
    if search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                CashPurchase.title.ilike(term),
                CashPurchase.reference_number.ilike(term),
                CashPurchase.receipt_number.ilike(term),
                CashPurchase.supplier_name.ilike(term),
                CashPurchase.notes.ilike(term),
            )
        )

    # ── Purchase Date Range ──────────────────────────────────────────────────
    if date_from:
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            stmt = stmt.where(CashPurchase.purchase_date >= d_from)
        except ValueError:
            pass
    if date_to:
        try:
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
            stmt = stmt.where(CashPurchase.purchase_date <= d_to)
        except ValueError:
            pass

    # ── Amount Range ─────────────────────────────────────────────────────────
    if amount_min:
        try:
            a_min = Decimal(amount_min)
            stmt = stmt.where(CashPurchase.amount >= a_min)
        except (InvalidOperation, ValueError):
            pass
    if amount_max:
        try:
            a_max = Decimal(amount_max)
            stmt = stmt.where(CashPurchase.amount <= a_max)
        except (InvalidOperation, ValueError):
            pass

    # ── Supplier Filter ──────────────────────────────────────────────────────
    if vendor_id:
        stmt = stmt.where(CashPurchase.vendor_id == vendor_id)

    # ── Sorting ──────────────────────────────────────────────────────────────
    sort_options = {
        "purchase_date_desc": (CashPurchase.purchase_date.desc(), CashPurchase.created_at.desc()),
        "purchase_date_asc": (CashPurchase.purchase_date.asc(), CashPurchase.created_at.asc()),
        "amount_desc": (CashPurchase.amount.desc(), CashPurchase.purchase_date.desc()),
        "amount_asc": (CashPurchase.amount.asc(), CashPurchase.purchase_date.desc()),
        "created_at_desc": (CashPurchase.created_at.desc(),),
    }
    stmt = stmt.order_by(*sort_options.get(sort, (CashPurchase.purchase_date.desc(), CashPurchase.created_at.desc())))

    # ── Pagination ───────────────────────────────────────────────────────────
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = await db.scalar(count_stmt) or 0
    total_pages = max(1, (total_count + page_size - 1) // page_size)

    stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    result = await db.execute(stmt)
    purchases = list(result.scalars().all())

    # Pre-fetch filter dropdown options
    vendors_res = await db.execute(
        select(Vendor).where(Vendor.is_active == True).order_by(Vendor.company_name)
    )
    all_vendors = vendors_res.scalars().all()

    users_res = await db.execute(
        select(UserProfile).where(UserProfile.is_active == True).order_by(UserProfile.full_name)
    )
    all_users = users_res.scalars().all()

    # Total expenditure sum for filtered view
    sum_stmt = select(func.coalesce(func.sum(CashPurchase.amount), Decimal(0))).select_from(
        stmt.limit(None).offset(None).subquery()
    )
    total_amount_sum = await db.scalar(sum_stmt) or Decimal(0)

    return templates.TemplateResponse(
        request,
        "cash_purchases/list.html",
        {
            "user": user,
            "purchases": purchases,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "search": search,
            "date_from": date_from,
            "date_to": date_to,
            "amount_min": amount_min,
            "amount_max": amount_max,
            "vendor_id": vendor_id,
            "created_by": created_by,
            "sort": sort,
            "all_vendors": all_vendors,
            "all_users": all_users,
            "total_amount_sum": total_amount_sum,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_cash_purchase_page(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    vendors_res = await db.execute(
        select(Vendor).where(Vendor.is_active == True).order_by(Vendor.company_name)
    )
    categories_res = await db.execute(
        select(Category).order_by(Category.name)
    )

    today_str = get_dhaka_today().strftime("%Y-%m-%d")

    return templates.TemplateResponse(
        request,
        "cash_purchases/form.html",
        {
            "user": user,
            "purchase": None,
            "vendors": vendors_res.scalars().all(),
            "categories": categories_res.scalars().all(),
            "today_str": today_str,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/new")
async def create_cash_purchase(
    request: Request,
    title: str = Form(""),
    amount: str = Form(""),
    purchase_date: str = Form(""),
    receipt_number: str = Form(""),
    vendor_id: str = Form(""),
    supplier_name: str = Form(""),
    category_id: str = Form(""),
    notes: str = Form(""),
    receipt_image: UploadFile = File(None),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    title = title.strip()
    if not title:
        return RedirectResponse(url="/cash-purchases/new?error=Title+is+required", status_code=303)

    # Validate positive Decimal amount
    try:
        clean_amount = Decimal(amount.strip().replace(",", ""))
        if clean_amount <= Decimal(0):
            raise ValueError()
    except Exception:
        return RedirectResponse(url="/cash-purchases/new?error=Amount+must+be+greater+than+zero", status_code=303)

    # Validate Purchase Date
    try:
        clean_purchase_date = datetime.strptime(purchase_date.strip(), "%Y-%m-%d").date()
    except Exception:
        clean_purchase_date = get_dhaka_today()

    # ── Validate Mandatory Physical Slip Upload ──────────────────────────────
    if not receipt_image or not receipt_image.filename:
        return RedirectResponse(
            url="/cash-purchases/new?error=Physical+receipt+or+slip+image+is+strictly+mandatory",
            status_code=303,
        )

    file_bytes = await receipt_image.read()
    if len(file_bytes) == 0:
        return RedirectResponse(
            url="/cash-purchases/new?error=Physical+receipt+or+slip+image+file+is+empty",
            status_code=303,
        )

    ext = (receipt_image.filename.rsplit(".", 1)[-1] if "." in receipt_image.filename else "jpg").lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return RedirectResponse(
            url=f"/cash-purchases/new?error=Invalid+file+type.+Allowed:+{', '.join(ALLOWED_IMAGE_EXTENSIONS)}",
            status_code=303,
        )

    purchase_id = str(uuid.uuid4())
    remote_path = f"cash_purchases/{purchase_id}/{uuid.uuid4().hex[:8]}.{ext}"
    content_type = receipt_image.content_type or "image/jpeg"
    receipt_url = await upload_file("", remote_path, file_bytes, content_type)

    if not receipt_url:
        return RedirectResponse(
            url="/cash-purchases/new?error=Failed+to+upload+receipt+image",
            status_code=303,
        )

    # Generate human-friendly reference number
    ref_no = generate_reference_number(clean_purchase_date)

    # Resolve supplier naming
    clean_vendor_id = vendor_id.strip() if vendor_id.strip() else None
    clean_supplier_name = supplier_name.strip() if supplier_name.strip() else None
    if clean_vendor_id:
        v_res = await db.execute(select(Vendor).where(Vendor.id == clean_vendor_id))
        v_obj = v_res.scalar_one_or_none()
        if v_obj and not clean_supplier_name:
            clean_supplier_name = v_obj.company_name

    clean_category_id = category_id.strip() if category_id.strip() else None
    clean_receipt_no = receipt_number.strip() if receipt_number.strip() else None
    clean_notes = notes.strip() if notes.strip() else None

    # Check for possible duplicates
    dup_stmt = select(CashPurchase).where(
        CashPurchase.amount == clean_amount,
        CashPurchase.purchase_date == clean_purchase_date,
    )
    if clean_receipt_no:
        dup_stmt = dup_stmt.where(CashPurchase.receipt_number == clean_receipt_no)
    dup_res = await db.execute(dup_stmt)
    is_duplicate = dup_res.scalar_one_or_none() is not None

    record = CashPurchase(
        id=purchase_id,
        reference_number=ref_no,
        title=title,
        amount=clean_amount,
        currency="BDT",
        purchase_date=clean_purchase_date,
        receipt_url=receipt_url,
        receipt_number=clean_receipt_no,
        vendor_id=clean_vendor_id,
        supplier_name=clean_supplier_name,
        category_id=clean_category_id,
        notes=clean_notes,
        created_by=user.id,
    )
    db.add(record)
    await db.flush()

    # ── Audit Log ────────────────────────────────────────────────────────────
    supplier_disp = clean_supplier_name or "N/A"
    await log_action(
        db,
        actor=user,
        action="CASH_PURCHASE_CREATED",
        entity_type="cash_purchase",
        entity_id=record.id,
        entity_label=record.title,
        notes=(
            f"Reference: {record.reference_number}. Amount: BDT {clean_amount:.2f}. "
            f"Purchase Date: {clean_purchase_date}. Supplier: {supplier_disp}. "
            f"Receipt Memo: {clean_receipt_no or 'None'}. "
            f"{'Possible duplicate detected.' if is_duplicate else ''}"
        ).strip(),
    )

    await db.commit()
    success_msg = "Cash+purchase+recorded+successfully"
    if is_duplicate:
        success_msg += "+(Notice:+A+purchase+with+similar+amount+and+date+already+exists)"
    return RedirectResponse(url=f"/cash-purchases/{record.id}?success={success_msg}", status_code=303)


@router.get("/{purchase_id}", response_class=HTMLResponse)
async def view_cash_purchase(
    request: Request,
    purchase_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(
        select(CashPurchase)
        .options(
            selectinload(CashPurchase.creator),
            selectinload(CashPurchase.updater),
            selectinload(CashPurchase.vendor),
            selectinload(CashPurchase.category),
        )
        .where(CashPurchase.id == purchase_id)
    )
    purchase = result.scalar_one_or_none()
    if not purchase:
        await db.commit()
        return RedirectResponse(url="/cash-purchases?error=Record+not+found", status_code=303)

    # Visibility permission: creator or users with global visibility
    if not user.can_see_all_requisitions and purchase.created_by != user.id:
        await db.commit()
        return RedirectResponse(url="/cash-purchases?error=Permission+denied", status_code=303)

    # Format timestamps
    bst_created = "N/A"
    if purchase.created_at:
        try:
            dt = purchase.created_at.astimezone(ZoneInfo("Asia/Dhaka")) if purchase.created_at.tzinfo else purchase.created_at
            bst_created = dt.strftime("%B %d, %Y at %I:%M %p BST")
        except Exception:
            bst_created = purchase.created_at.strftime("%B %d, %Y (%I:%M %p)")

    can_edit = bool(user.has_management_authority or user.role == UserRole.ADMIN or purchase.created_by == user.id)

    return templates.TemplateResponse(
        request,
        "cash_purchases/detail.html",
        {
            "user": user,
            "purchase": purchase,
            "bst_created": bst_created,
            "can_edit": can_edit,
        },
    )


@router.get("/{purchase_id}/edit", response_class=HTMLResponse)
async def edit_cash_purchase_page(
    request: Request,
    purchase_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(
        select(CashPurchase)
        .options(
            selectinload(CashPurchase.vendor),
            selectinload(CashPurchase.category),
        )
        .where(CashPurchase.id == purchase_id)
    )
    purchase = result.scalar_one_or_none()
    if not purchase:
        await db.commit()
        return RedirectResponse(url="/cash-purchases?error=Record+not+found", status_code=303)

    # Edit permission: creator or management/admin
    if not (user.has_management_authority or user.role == UserRole.ADMIN or purchase.created_by == user.id):
        await db.commit()
        return RedirectResponse(url=f"/cash-purchases/{purchase_id}?error=Permission+denied", status_code=303)

    vendors_res = await db.execute(
        select(Vendor).where(Vendor.is_active == True).order_by(Vendor.company_name)
    )
    categories_res = await db.execute(
        select(Category).order_by(Category.name)
    )

    return templates.TemplateResponse(
        request,
        "cash_purchases/form.html",
        {
            "user": user,
            "purchase": purchase,
            "vendors": vendors_res.scalars().all(),
            "categories": categories_res.scalars().all(),
            "today_str": purchase.purchase_date.strftime("%Y-%m-%d"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/{purchase_id}/edit")
async def update_cash_purchase(
    request: Request,
    purchase_id: str,
    title: str = Form(""),
    amount: str = Form(""),
    purchase_date: str = Form(""),
    receipt_number: str = Form(""),
    vendor_id: str = Form(""),
    supplier_name: str = Form(""),
    category_id: str = Form(""),
    notes: str = Form(""),
    receipt_image: UploadFile = File(None),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CashPurchase).where(CashPurchase.id == purchase_id))
    purchase = result.scalar_one_or_none()
    if not purchase:
        return RedirectResponse(url="/cash-purchases?error=Record+not+found", status_code=303)

    # Edit permission: creator or management/admin
    if not (user.has_management_authority or user.role == UserRole.ADMIN or purchase.created_by == user.id):
        return RedirectResponse(url=f"/cash-purchases/{purchase_id}?error=Permission+denied", status_code=303)

    title = title.strip()
    if not title:
        return RedirectResponse(url=f"/cash-purchases/{purchase_id}/edit?error=Title+is+required", status_code=303)

    try:
        clean_amount = Decimal(amount.strip().replace(",", ""))
        if clean_amount <= Decimal(0):
            raise ValueError()
    except Exception:
        return RedirectResponse(url=f"/cash-purchases/{purchase_id}/edit?error=Amount+must+be+greater+than+zero", status_code=303)

    try:
        clean_purchase_date = datetime.strptime(purchase_date.strip(), "%Y-%m-%d").date()
    except Exception:
        clean_purchase_date = purchase.purchase_date

    # Handle replacement slip upload if provided
    new_receipt_url = None
    if receipt_image and receipt_image.filename:
        file_bytes = await receipt_image.read()
        if len(file_bytes) > 0:
            ext = (receipt_image.filename.rsplit(".", 1)[-1] if "." in receipt_image.filename else "jpg").lower()
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                remote_path = f"cash_purchases/{purchase.id}/{uuid.uuid4().hex[:8]}.{ext}"
                content_type = receipt_image.content_type or "image/jpeg"
                new_receipt_url = await upload_file("", remote_path, file_bytes, content_type)

    changes = []
    if purchase.title != title:
        changes.append(f"Title: '{purchase.title}' -> '{title}'")
        purchase.title = title

    if purchase.amount != clean_amount:
        changes.append(f"Amount: BDT {purchase.amount:.2f} -> BDT {clean_amount:.2f}")
        purchase.amount = clean_amount

    if purchase.purchase_date != clean_purchase_date:
        changes.append(f"Purchase Date: {purchase.purchase_date} -> {clean_purchase_date}")
        purchase.purchase_date = clean_purchase_date

    clean_receipt_no = receipt_number.strip() if receipt_number.strip() else None
    if purchase.receipt_number != clean_receipt_no:
        changes.append(f"Receipt No: '{purchase.receipt_number}' -> '{clean_receipt_no}'")
        purchase.receipt_number = clean_receipt_no

    clean_vendor_id = vendor_id.strip() if vendor_id.strip() else None
    clean_supplier_name = supplier_name.strip() if supplier_name.strip() else None
    if clean_vendor_id:
        v_res = await db.execute(select(Vendor).where(Vendor.id == clean_vendor_id))
        v_obj = v_res.scalar_one_or_none()
        if v_obj and not clean_supplier_name:
            clean_supplier_name = v_obj.company_name

    purchase.vendor_id = clean_vendor_id
    purchase.supplier_name = clean_supplier_name
    purchase.category_id = category_id.strip() if category_id.strip() else None
    purchase.notes = notes.strip() if notes.strip() else None

    if new_receipt_url:
        purchase.receipt_url = new_receipt_url
        changes.append("Receipt image replaced with new upload")

    purchase.updated_by = user.id
    purchase.updated_at = datetime.now(ZoneInfo("UTC"))
    await db.flush()

    # ── Audit Log ────────────────────────────────────────────────────────────
    if changes:
        await log_action(
            db,
            actor=user,
            action="CASH_PURCHASE_UPDATED",
            entity_type="cash_purchase",
            entity_id=purchase.id,
            entity_label=purchase.title,
            notes=f"Ref: {purchase.reference_number}. Updates: {'; '.join(changes)}",
        )

    await db.commit()
    return RedirectResponse(url=f"/cash-purchases/{purchase.id}?success=Cash+purchase+updated+successfully", status_code=303)


@router.post("/{purchase_id}/delete")
async def delete_cash_purchase(
    purchase_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CashPurchase).where(CashPurchase.id == purchase_id))
    purchase = result.scalar_one_or_none()
    if not purchase:
        await db.commit()
        return RedirectResponse(url="/cash-purchases?error=Record+not+found", status_code=303)

    if not (user.has_management_authority or user.role == UserRole.ADMIN or purchase.created_by == user.id):
        await db.commit()
        return RedirectResponse(url=f"/cash-purchases/{purchase_id}?error=Permission+denied", status_code=303)

    ref_no = purchase.reference_number
    title = purchase.title

    await db.delete(purchase)

    # ── Audit Log ────────────────────────────────────────────────────────────
    await log_action(
        db,
        actor=user,
        action="CASH_PURCHASE_DELETED",
        entity_type="cash_purchase",
        entity_id=purchase_id,
        entity_label=title,
        notes=f"Reference: {ref_no} ({title}) deleted by {user.full_name}.",
    )

    await db.commit()
    return RedirectResponse(url="/cash-purchases?success=Record+deleted+successfully", status_code=303)
