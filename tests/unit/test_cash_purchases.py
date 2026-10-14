import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import select

from app.auth.models import UserProfile, UserRole
from app.audit.models import AuditLog
from app.audit.service import log_action
from app.cash_purchases.models import CashPurchase
from app.cash_purchases.routes import (
    ALLOWED_IMAGE_EXTENSIONS,
    generate_reference_number,
    get_dhaka_today,
)
from app.vendors.models import Vendor
from app.categories.models import Category


def test_reference_number_format():
    test_date = date(2026, 10, 14)
    ref = generate_reference_number(test_date)
    assert ref.startswith("CP-20261014-")
    assert len(ref) == 3 + 8 + 1 + 6  # "CP-" + "20261014" + "-" + 6 hex chars
    assert ref[3:11] == "20261014"


def test_dhaka_today_is_date():
    today = get_dhaka_today()
    assert isinstance(today, date)
    assert today == datetime.now(ZoneInfo("Asia/Dhaka")).date()


def test_allowed_image_extensions():
    assert "jpg" in ALLOWED_IMAGE_EXTENSIONS
    assert "jpeg" in ALLOWED_IMAGE_EXTENSIONS
    assert "png" in ALLOWED_IMAGE_EXTENSIONS
    assert "webp" in ALLOWED_IMAGE_EXTENSIONS
    assert "pdf" in ALLOWED_IMAGE_EXTENSIONS
    assert "exe" not in ALLOWED_IMAGE_EXTENSIONS
    assert "sh" not in ALLOWED_IMAGE_EXTENSIONS


@pytest.mark.asyncio
async def test_cash_purchase_model_creation(async_db):
    # Setup creator user
    user = UserProfile(
        id="usr-proc-001",
        email="procurement@wenerbd.com",
        username="proc1",
        full_name="Procurement Officer 1",
        role=UserRole.PROCUREMENT,
    )
    async_db.add(user)
    await async_db.flush()

    # Create Cash Purchase record
    purchase = CashPurchase(
        id="cp-001",
        reference_number="CP-20261014-A1B2C3",
        title="Emergency Generator Fuel Purchase",
        amount=Decimal("15450.50"),
        currency="BDT",
        purchase_date=date(2026, 10, 14),
        receipt_url="https://storage.wenerbd.cloud/cash_purchases/cp-001/slip.jpg",
        receipt_number="MEMO-98712",
        supplier_name="Padma Oil Station",
        created_by=user.id,
    )
    async_db.add(purchase)
    await async_db.commit()

    # Query back
    res = await async_db.execute(select(CashPurchase).where(CashPurchase.id == "cp-001"))
    fetched = res.scalar_one()

    assert fetched.title == "Emergency Generator Fuel Purchase"
    assert fetched.amount == Decimal("15450.50")
    assert fetched.currency == "BDT"
    assert fetched.purchase_date == date(2026, 10, 14)
    assert fetched.receipt_url == "https://storage.wenerbd.cloud/cash_purchases/cp-001/slip.jpg"
    assert fetched.receipt_number == "MEMO-98712"
    assert fetched.supplier_name == "Padma Oil Station"
    assert fetched.created_by == "usr-proc-001"
    assert fetched.created_at is not None
    assert fetched.creator.full_name == "Procurement Officer 1"


@pytest.mark.asyncio
async def test_cash_purchase_positive_amount_and_purchase_date_distinction(async_db):
    user = UserProfile(
        id="usr-proc-002",
        email="proc2@wenerbd.com",
        username="proc2",
        full_name="Procurement Officer 2",
        role=UserRole.PROCUREMENT,
    )
    async_db.add(user)
    await async_db.flush()

    # Purchase Date is in the past, record created now
    past_purchase_date = date(2026, 10, 10)
    purchase = CashPurchase(
        id="cp-002",
        reference_number="CP-20261010-F4E5D6",
        title="Hardware Store Fasteners & Drill Bits",
        amount=Decimal("2800.00"),
        currency="BDT",
        purchase_date=past_purchase_date,
        receipt_url="https://storage.wenerbd.cloud/cash_purchases/cp-002/memo.png",
        created_by=user.id,
    )
    async_db.add(purchase)
    await async_db.commit()

    res = await async_db.execute(select(CashPurchase).where(CashPurchase.id == "cp-002"))
    fetched = res.scalar_one()

    # Amount must be strictly positive
    assert fetched.amount > Decimal("0")
    # Purchase Date differs from created_at server date
    assert fetched.purchase_date == past_purchase_date
    assert fetched.created_at.date() >= past_purchase_date


@pytest.mark.asyncio
async def test_cash_purchase_visibility_permissions(async_db):
    # User 1: Regular Procurement Officer (can_view_all_requisitions=False)
    officer1 = UserProfile(
        id="usr-p1",
        email="p1@wenerbd.com",
        username="p1",
        full_name="Officer 1",
        role=UserRole.PROCUREMENT,
        can_view_all_requisitions=False,
    )
    # User 2: Procurement Officer with See All (can_view_all_requisitions=True)
    officer2 = UserProfile(
        id="usr-p2",
        email="p2@wenerbd.com",
        username="p2",
        full_name="Officer 2",
        role=UserRole.PROCUREMENT,
        can_view_all_requisitions=True,
    )
    # User 3: Management
    mgmt = UserProfile(
        id="usr-mgmt",
        email="mgmt@wenerbd.com",
        username="mgmt",
        full_name="Manager",
        role=UserRole.MANAGEMENT,
    )
    async_db.add_all([officer1, officer2, mgmt])
    await async_db.flush()

    # Record created by officer 1
    cp1 = CashPurchase(
        id="cp-p1",
        reference_number="CP-20261014-000001",
        title="Officer 1 Purchase",
        amount=Decimal("500.00"),
        purchase_date=date(2026, 10, 14),
        receipt_url="https://storage.wenerbd.cloud/cp1.jpg",
        created_by=officer1.id,
    )
    # Record created by officer 2
    cp2 = CashPurchase(
        id="cp-p2",
        reference_number="CP-20261014-000002",
        title="Officer 2 Purchase",
        amount=Decimal("1200.00"),
        purchase_date=date(2026, 10, 14),
        receipt_url="https://storage.wenerbd.cloud/cp2.jpg",
        created_by=officer2.id,
    )
    async_db.add_all([cp1, cp2])
    await async_db.commit()

    # Query for Officer 1 (no See All) -> only their own purchases
    stmt_p1 = select(CashPurchase)
    if not officer1.can_see_all_requisitions:
        stmt_p1 = stmt_p1.where(CashPurchase.created_by == officer1.id)
    res_p1 = await async_db.execute(stmt_p1)
    p1_records = res_p1.scalars().all()
    assert len(p1_records) == 1
    assert p1_records[0].id == "cp-p1"

    # Query for Officer 2 (has See All) -> sees all purchases
    stmt_p2 = select(CashPurchase)
    if not officer2.can_see_all_requisitions:
        stmt_p2 = stmt_p2.where(CashPurchase.created_by == officer2.id)
    res_p2 = await async_db.execute(stmt_p2)
    p2_records = res_p2.scalars().all()
    assert len(p2_records) == 2

    # Query for Management -> sees all purchases
    stmt_mgmt = select(CashPurchase)
    if not mgmt.can_see_all_requisitions:
        stmt_mgmt = stmt_mgmt.where(CashPurchase.created_by == mgmt.id)
    res_mgmt = await async_db.execute(stmt_mgmt)
    mgmt_records = res_mgmt.scalars().all()
    assert len(mgmt_records) == 2


@pytest.mark.asyncio
async def test_cash_purchase_edit_and_delete_permissions(async_db):
    officer1 = UserProfile(
        id="usr-p10",
        email="p10@wenerbd.com",
        username="p10",
        full_name="Officer 10",
        role=UserRole.PROCUREMENT,
        can_view_all_requisitions=False,
    )
    officer2 = UserProfile(
        id="usr-p20",
        email="p20@wenerbd.com",
        username="p20",
        full_name="Officer 20",
        role=UserRole.PROCUREMENT,
        can_view_all_requisitions=False,
    )
    admin = UserProfile(
        id="usr-admin",
        email="admin@wenerbd.com",
        username="admin",
        full_name="System Admin",
        role=UserRole.ADMIN,
    )
    async_db.add_all([officer1, officer2, admin])
    await async_db.flush()

    cp = CashPurchase(
        id="cp-perm",
        reference_number="CP-20261014-999999",
        title="Permission Check Purchase",
        amount=Decimal("350.00"),
        purchase_date=date(2026, 10, 14),
        receipt_url="https://storage.wenerbd.cloud/perm.jpg",
        created_by=officer1.id,
    )
    async_db.add(cp)
    await async_db.commit()

    # Creator (officer1) can edit
    can_officer1_edit = bool(
        officer1.has_management_authority or officer1.role == UserRole.ADMIN or cp.created_by == officer1.id
    )
    assert can_officer1_edit is True

    # Another officer (officer2) CANNOT edit
    can_officer2_edit = bool(
        officer2.has_management_authority or officer2.role == UserRole.ADMIN or cp.created_by == officer2.id
    )
    assert can_officer2_edit is False

    # Admin CAN edit
    can_admin_edit = bool(
        admin.has_management_authority or admin.role == UserRole.ADMIN or cp.created_by == admin.id
    )
    assert can_admin_edit is True


@pytest.mark.asyncio
async def test_cash_purchase_audit_log_generation(async_db):
    user = UserProfile(
        id="usr-audit-test",
        email="auditor@wenerbd.com",
        username="auditor",
        full_name="Audit Tester",
        role=UserRole.PROCUREMENT,
    )
    async_db.add(user)
    await async_db.flush()

    # 1. Test creation audit log
    cp = CashPurchase(
        id="cp-audit-01",
        reference_number="CP-20261014-AUDIT1",
        title="Audit Test Item",
        amount=Decimal("1200.00"),
        purchase_date=date(2026, 10, 14),
        receipt_url="https://storage.wenerbd.cloud/audit.jpg",
        receipt_number="REC-101",
        supplier_name="Audit Supplier",
        created_by=user.id,
    )
    async_db.add(cp)
    await async_db.flush()

    await log_action(
        async_db,
        actor=user,
        action="CASH_PURCHASE_CREATED",
        entity_type="cash_purchase",
        entity_id=cp.id,
        entity_label=cp.title,
        notes=f"Reference: {cp.reference_number}. Amount: BDT {cp.amount:.2f}.",
    )
    await async_db.commit()

    # Verify audit log for creation
    res = await async_db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "cash_purchase",
            AuditLog.entity_id == cp.id,
            AuditLog.action == "CASH_PURCHASE_CREATED",
        )
    )
    log_entry = res.scalar_one()
    assert log_entry.action == "CASH_PURCHASE_CREATED"
    assert log_entry.actor_id == user.id
    assert log_entry.actor_name == user.full_name
    assert "CP-20261014-AUDIT1" in log_entry.notes
    assert "1200.00" in log_entry.notes

    # 2. Test update audit log
    cp.amount = Decimal("1350.00")
    await log_action(
        async_db,
        actor=user,
        action="CASH_PURCHASE_UPDATED",
        entity_type="cash_purchase",
        entity_id=cp.id,
        entity_label=cp.title,
        notes=f"Ref: {cp.reference_number}. Updates: Amount: BDT 1200.00 -> BDT 1350.00",
    )
    await async_db.commit()

    res_update = await async_db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "cash_purchase",
            AuditLog.entity_id == cp.id,
            AuditLog.action == "CASH_PURCHASE_UPDATED",
        )
    )
    update_entry = res_update.scalar_one()
    assert "BDT 1200.00 -> BDT 1350.00" in update_entry.notes

    # 3. Test deletion audit log
    ref_no = cp.reference_number
    title = cp.title
    await async_db.delete(cp)
    await log_action(
        async_db,
        actor=user,
        action="CASH_PURCHASE_DELETED",
        entity_type="cash_purchase",
        entity_id="cp-audit-01",
        entity_label=title,
        notes=f"Reference: {ref_no} ({title}) deleted by {user.full_name}.",
    )
    await async_db.commit()

    res_del = await async_db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "cash_purchase",
            AuditLog.entity_id == "cp-audit-01",
            AuditLog.action == "CASH_PURCHASE_DELETED",
        )
    )
    del_entry = res_del.scalar_one()
    assert "deleted by Audit Tester" in del_entry.notes


@pytest.mark.asyncio
async def test_duplicate_cash_purchase_warning_detection(async_db):
    user = UserProfile(
        id="usr-dup",
        email="dup@wenerbd.com",
        username="dup",
        full_name="Duplicate Tester",
        role=UserRole.PROCUREMENT,
    )
    async_db.add(user)
    await async_db.flush()

    p_date = date(2026, 10, 14)
    amount = Decimal("4500.00")
    memo = "MEMO-12345"

    cp_original = CashPurchase(
        id="cp-orig",
        reference_number="CP-20261014-ORIG01",
        title="Original Electrical Cables",
        amount=amount,
        purchase_date=p_date,
        receipt_url="https://storage.wenerbd.cloud/cable.jpg",
        receipt_number=memo,
        created_by=user.id,
    )
    async_db.add(cp_original)
    await async_db.commit()

    # Query duplicate detection
    dup_stmt = select(CashPurchase).where(
        CashPurchase.amount == amount,
        CashPurchase.purchase_date == p_date,
        CashPurchase.receipt_number == memo,
    )
    dup_res = await async_db.execute(dup_stmt)
    is_duplicate = dup_res.scalar_one_or_none() is not None
    assert is_duplicate is True

    # Query with different amount -> not duplicate
    diff_stmt = select(CashPurchase).where(
        CashPurchase.amount == Decimal("9999.00"),
        CashPurchase.purchase_date == p_date,
        CashPurchase.receipt_number == memo,
    )
    diff_res = await async_db.execute(diff_stmt)
    assert diff_res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_route_unauthenticated_redirects_to_login():
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/cash-purchases", follow_redirects=False)
        assert res.status_code == 302
        assert "/auth/login" in res.headers["location"]


@pytest.mark.asyncio
async def test_route_create_cash_purchase_validations(async_db, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.dependencies import get_current_user
    from app.database import get_db

    test_user = UserProfile(
        id="usr-route-tester",
        email="routetester@wenerbd.com",
        username="rtester",
        full_name="Route Tester",
        role=UserRole.PROCUREMENT,
        can_view_all_requisitions=True,
    )
    async_db.add(test_user)
    await async_db.commit()

    # Override dependencies
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_db] = lambda: async_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Missing title
            res = await client.post(
                "/cash-purchases/new",
                data={"title": "", "amount": "100.00", "purchase_date": "2026-10-14"},
                follow_redirects=False,
            )
            assert res.status_code == 303
            assert "Title+is+required" in res.headers["location"]

            # 2. Invalid zero / negative amount
            res = await client.post(
                "/cash-purchases/new",
                data={"title": "Office Snacks", "amount": "0", "purchase_date": "2026-10-14"},
                follow_redirects=False,
            )
            assert res.status_code == 303
            assert "Amount+must+be+greater+than+zero" in res.headers["location"]

            # 3. Missing physical receipt image upload
            res = await client.post(
                "/cash-purchases/new",
                data={"title": "Office Snacks", "amount": "250.00", "purchase_date": "2026-10-14"},
                follow_redirects=False,
            )
            assert res.status_code == 303
            assert "Physical+receipt+or+slip+image+is+strictly+mandatory" in res.headers["location"]

            # 4. Invalid file extension (.exe)
            files = {"receipt_image": ("badfile.exe", b"fake binary payload", "application/octet-stream")}
            res = await client.post(
                "/cash-purchases/new",
                data={"title": "Office Supplies", "amount": "500.00", "purchase_date": "2026-10-14"},
                files=files,
                follow_redirects=False,
            )
            assert res.status_code == 303
            assert "Invalid+file+type" in res.headers["location"]

            # 5. Successful creation with physical receipt image
            valid_files = {"receipt_image": ("slip.jpg", b"fake jpeg image payload", "image/jpeg")}
            res = await client.post(
                "/cash-purchases/new",
                data={
                    "title": "Emergency Printer Paper",
                    "amount": "1800.00",
                    "purchase_date": "2026-10-14",
                    "receipt_number": "MEMO-54321",
                    "supplier_name": "New Market Stationers",
                    "notes": "Purchased in cash from store",
                },
                files=valid_files,
                follow_redirects=False,
            )
            assert res.status_code == 303
            assert "/cash-purchases/" in res.headers["location"]
            assert "Cash+purchase+recorded+successfully" in res.headers["location"]

            # Follow redirect to detail page
            detail_url = res.headers["location"]
            res_detail = await client.get(detail_url)
            assert res_detail.status_code == 200
            assert "Emergency Printer Paper" in res_detail.text
            assert "1800.00" in res_detail.text
            assert "New Market Stationers" in res_detail.text
            assert "MEMO-54321" in res_detail.text
    finally:
        app.dependency_overrides.clear()

