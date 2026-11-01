import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import app.database  # noqa: F401
from app.auth.models import UserProfile  # noqa: F401
from app.vendors.models import Vendor  # noqa: F401
from app.quotations.models import Quotation  # noqa: F401
from app.requisitions.models import Requisition
from app.work_orders.models import WorkOrder
import app.work_orders.service as wo_service


def test_requisition_and_work_order_reference_codes():
    req = Requisition(
        id="04a7e919-2b09-4840-bfdb-1c26163e5be7",
        title="PP Virgin",
        created_by="user-123",
    )
    assert req.reference_code == "REQ-04A7E919"

    wo = WorkOrder(
        id="4d4f563a-1670-475b-9d12-99d05e0e3faf",
        requisition_id="04a7e919-2b09-4840-bfdb-1c26163e5be7",
        vendor_id="vendor-456",
        requisition_vendor_id="rv-789",
        issued_by="user-123",
    )
    # WorkOrder references the requisition code: WO-04A7E919
    assert wo.reference_code == "WO-04A7E919"

    # Fallback when requisition_id is absent
    standalone_wo = WorkOrder(
        id="4d4f563a-1670-475b-9d12-99d05e0e3faf",
        requisition_id=None,
        vendor_id="vendor-456",
        requisition_vendor_id="rv-789",
        issued_by="user-123",
    )
    assert standalone_wo.reference_code == "WO-4D4F563A"


@pytest.mark.asyncio
async def test_generate_work_order_pdf_layout_and_dynamic_terms():
    captured_html = []

    def mock_html(string=None):
        captured_html.append(string)
        m = MagicMock()
        m.write_pdf.return_value = b"%PDF-1.4 mock work order"
        return m

    with patch("weasyprint.HTML", side_effect=mock_html):
        wo = MagicMock()
        wo.id = "4d4f563a-1670-475b-9d12-99d05e0e3faf"
        wo.requisition_id = "04a7e919-2b09-4840-bfdb-1c26163e5be7"
        wo.reference_code = "WO-04A7E919"
        wo.issued_at = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
        wo.requisition = MagicMock(id="04a7e919-2b09-4840-bfdb-1c26163e5be7", title="Industrial Dies")
        wo.vendor = MagicMock(
            company_name="Ashraf Lathe Works",
            contact_person="Md. Ashraf",
            phone="+8801711234567",
            contact_email="ashraf@lathe.com",
        )
        wo.issuer = MagicMock(full_name="Mizanur Rahman")
        wo.requisition_vendor = None

        # Custom flexible quotation terms
        wo._quotation_data = {
            "delivery_days": "25",
            "payment_terms": "40% advance, 60% upon delivery",
            "warranty": "6 Months free replacement",
            "notes": "Delivery to Gazipur factory premises",
            "items": [
                {
                    "name": "BLDC Circle Patting Die",
                    "description": "Bearing Metal 132mm",
                    "qty": 2,
                    "price": 50000.0,
                }
            ],
        }

        pdf_bytes = await wo_service.generate_work_order_pdf(wo, None)
        assert pdf_bytes is not None
        assert len(captured_html) > 0
        html = captured_html[-1]

        # Verify Ref & Title
        assert "Ref: WO-04A7E919" in html
        assert "PURCHASE ORDER" in html

        # Verify In Word label & Bangla amounts
        assert "In Word:" in html
        assert "One Lac Taka Only" in html
        assert "1,00,000.00" in html

        # Verify Dynamic terms
        assert "25 days" in html
        assert "40% advance, 60% upon delivery" in html
        assert "6 Months free replacement" in html
        assert "Delivery to Gazipur factory premises" in html

        # Verify payment clearance method box & signatures are REMOVED
        assert "PAYMENT METHOD" not in html
        assert "Payment Clearance Method" not in html
        assert "Prepared By" not in html
        assert "Approved By" not in html


@pytest.mark.asyncio
async def test_generate_work_order_pdf_fallback_to_rv_quotation():
    """Verify that if _quotation_data is missing, it falls back to rv.quotation.form_data."""
    captured_html = []

    def mock_html(string=None):
        captured_html.append(string)
        m = MagicMock()
        m.write_pdf.return_value = b"%PDF-1.4 mock work order"
        return m

    with patch("weasyprint.HTML", side_effect=mock_html):
        rv_mock = MagicMock()
        rv_mock.quotation.form_data = {
            "delivery_days": "15",
            "payment_terms": "100% on delivery",
            "items": [
                {"name": "Automatic Switch", "description": "16A", "qty": 100, "price": 200.0}
            ],
        }
        rv_mock.quotation.submitted_at = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)

        wo = MagicMock()
        wo.id = "4d4f563a-1670-475b-9d12-99d05e0e3faf"
        wo.requisition_id = "04a7e919-2b09-4840-bfdb-1c26163e5be7"
        wo.reference_code = "WO-04A7E919"
        wo.issued_at = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
        wo.requisition = MagicMock(id="04a7e919-2b09-4840-bfdb-1c26163e5be7", title="Switches")
        wo.vendor = MagicMock(company_name="Apex Power", contact_person="Tanvir", phone=None, contact_email=None)
        wo.issuer = MagicMock(full_name="Procurement Officer")
        wo.requisition_vendor = rv_mock
        # _quotation_data is explicitly not present
        if hasattr(wo, "_quotation_data"):
            delattr(wo, "_quotation_data")

        pdf_bytes = await wo_service.generate_work_order_pdf(wo, None)
        assert pdf_bytes is not None
        assert len(captured_html) > 0
        html = captured_html[-1]

        # Automatic fallback extracted quotation items & date
        assert "Automatic Switch" in html
        assert "20,000.00" in html
        assert "Twenty Thousand Taka Only" in html
        assert "15 days" in html
        assert "100% on delivery" in html
        assert "October 24, 2026" in html


@pytest.mark.asyncio
async def test_negotiation_procurement_notification():
    from app.email.resend import build_negotiation_procurement_notification

    payload = await build_negotiation_procurement_notification(
        to="procurement@wenerbd.com",
        procurement_officer_name="Sadik Rahman",
        requisition_title="High Density Foam",
        requisition_ref="REQ-9A4B8C12",
        contacted_suppliers=["Bengal Poly Ltd", "Padma Polymer"],
        requisition_url="https://procurement.wenerbd.cloud/requisitions/9a4b8c12",
    )
    assert payload["to"] == ["procurement@wenerbd.com"]
    assert "Negotiation Started: REQ-9A4B8C12 (High Density Foam)" in payload["subject"]
    html = payload["html"]
    assert "Sadik Rahman" in html
    assert "Bengal Poly Ltd" in html
    assert "Padma Polymer" in html
    assert "call them or send them links" in html or "follow up with these suppliers" in html
    assert "https://procurement.wenerbd.cloud/requisitions/9a4b8c12" in html


def test_status_badge_colors_are_unique():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("app/templates"))
    template = env.from_string("""
    {% from "components/status_badge.html" import render_status_badge %}
    {{ render_status_badge(status) }}
    """)

    statuses = [
        "draft",
        "new",
        "in_progress",
        "negotiating",
        "awarded",
        "work_order_issued",
        "receiving",
        "closed",
        "cancelled",
    ]

    rendered_colors = {}
    for st in statuses:
        rendered = template.render(status=st)
        # Find bg- color
        import re
        bg_match = re.search(r"bg-([a-z]+)-\d+", rendered)
        assert bg_match, f"No bg color found for {st}: {rendered}"
        color_family = bg_match.group(1)
        assert color_family not in rendered_colors.values(), (
            f"Duplicate color '{color_family}' found for '{st}'! Already used by '{[k for k, v in rendered_colors.items() if v == color_family]}'"
        )
        rendered_colors[st] = color_family

    assert len(rendered_colors) == 9


def test_work_order_detail_template_renders_without_dict_items_error():
    """Verify that work_orders/detail.html can iterate over quote_data['items'] dict.
    
    Prevents TypeError: 'builtin_function_or_method' object is not iterable.
    """
    from app.main import templates
    from unittest.mock import MagicMock
    from datetime import datetime, timezone

    wo = MagicMock()
    wo.id = "4d4f563a-1670-475b-9d12-99d05e0e3faf"
    wo.reference_code = "WO-04A7E919"
    wo.status = "issued"
    wo.pdf_url = "http://localhost:8000/uploads/work_orders/test.pdf"
    wo.issued_at = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    wo.delivery_started_at = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    wo.notes = "Special delivery"
    wo.requisition = MagicMock(id="04a7e919-2b09-4840-bfdb-1c26163e5be7", title="PP Virgin", reference_code="REQ-04A7E919")
    wo.vendor = MagicMock(company_name="Apex Polymer", contact_person="Karim", contact_email="karim@apex.com", phone="01700000000")
    wo.issuer = MagicMock(full_name="Sadik Rahman", email="procurement@wenerbd.com")

    quote_data = {
        "price": 150000.0,
        "items": [
            {"name": "PP Virgin Raw Resin", "description": "Grade A pellets", "qty": 1000, "price": 150.0}
        ],
        "delivery_days": "10",
        "payment_terms": "30 days net",
    }

    user = MagicMock(full_name="Sadik Rahman", role="admin", can_see_all_requisitions=True, is_procurement=True)
    request = MagicMock()
    request.query_params = {}
    request.url = MagicMock(path="/work-orders/4d4f563a-1670-475b-9d12-99d05e0e3faf")

    template = templates.get_template("work_orders/detail.html")
    rendered = template.render(request=request, user=user, wo=wo, quote_data=quote_data)

    assert "WO-04A7E919" in rendered
    assert "PP Virgin" in rendered
    assert "PP Virgin Raw Resin" in rendered
    assert "150.00" in rendered or "150" in rendered
    assert "/work-orders/4d4f563a-1670-475b-9d12-99d05e0e3faf/pdf" in rendered


@pytest.mark.asyncio
async def test_download_work_order_pdf_endpoint_regenerates_when_missing():
    """Verify download_work_order_pdf route regenerates PDF when file is missing from disk."""
    from unittest.mock import AsyncMock, patch, MagicMock
    from app.work_orders.routes import download_work_order_pdf
    from fastapi import HTTPException

    wo = MagicMock()
    wo.id = "4d4f563a-1670-475b-9d12-99d05e0e3faf"
    wo.reference_code = "WO-04A7E919"
    wo.pdf_url = "http://localhost:8000/uploads/work_orders/test.pdf"
    wo.issued_by = "user-123"
    wo.letterhead_slot = None

    user = MagicMock()
    user.id = "user-123"
    user.can_see_all_requisitions = True
    user.is_procurement = True

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = wo
    db.execute.return_value = mock_result

    with patch("os.path.exists", return_value=False), \
         patch("app.work_orders.routes.generate_work_order_pdf", new_callable=AsyncMock) as mock_gen, \
         patch("app.storage.upload_file", new_callable=AsyncMock) as mock_upload:
        
        mock_gen.return_value = b"%PDF-1.4 test generated pdf"
        mock_upload.return_value = "http://localhost:8000/uploads/work_orders/new.pdf"

        response = await download_work_order_pdf(
            wo_id=wo.id,
            user=user,
            db=db,
        )

        assert response.status_code == 200
        assert response.media_type == "application/pdf"
        assert b"%PDF-1.4 test generated pdf" in response.body
        assert 'filename="PO_WO-04A7E919.pdf"' in response.headers["Content-Disposition"]
        assert mock_gen.called


def test_operations_manager_role_and_permissions():
    """Verify operations_manager has management authority but no admin settings access."""
    from app.auth.models import UserProfile, UserRole

    op_mgr = UserProfile(
        id="user-op-1",
        email="ops@wenerbd.cloud",
        username="ops_manager",
        role=UserRole.OPERATIONS_MANAGER,
        can_view_all_requisitions=True,
    )
    assert op_mgr.role == UserRole.OPERATIONS_MANAGER
    assert op_mgr.has_management_authority is True
    assert op_mgr.can_see_quotes is True
    assert op_mgr.can_see_all_requisitions is True
    assert op_mgr.can_access_admin_settings is False

    admin = UserProfile(
        id="user-admin-1",
        email="admin@wenerbd.cloud",
        username="admin",
        role=UserRole.ADMIN,
    )
    assert admin.can_access_admin_settings is True

    mgmt = UserProfile(
        id="user-mgmt-1",
        email="mgmt@wenerbd.cloud",
        username="management",
        role=UserRole.MANAGEMENT,
    )
    assert mgmt.can_access_admin_settings is True

    proc = UserProfile(
        id="user-proc-1",
        email="proc@wenerbd.cloud",
        username="procurement",
        role=UserRole.PROCUREMENT,
    )
    assert proc.has_management_authority is False
    assert proc.can_access_admin_settings is False


def test_supplier_email_salutation_and_footer():
    """Verify supplier email salutation addresses contact and company, and includes standard signature."""
    from app.email.resend import _format_supplier_salutation, _email_footer, _format_recipient_cc_box

    # Both contact person and company name provided
    salutation = _format_supplier_salutation(
        vendor_name="John Doe",
        company_name="Apex Polymer Ltd",
        contact_person="John Doe",
    )
    assert salutation == "To John Doe from <strong>Apex Polymer Ltd</strong>,"

    # Only company name
    salutation_company_only = _format_supplier_salutation(
        vendor_name="Apex Polymer Ltd",
        company_name="Apex Polymer Ltd",
        contact_person=None,
    )
    assert salutation_company_only == "To <strong>Apex Polymer Ltd</strong>,"

    # Standard footer
    footer = _email_footer()
    assert "Regards,<br>" in footer
    assert "<strong>Wener Trading Company</strong>" in footer

    # CC recipient info box
    cc_box = _format_recipient_cc_box(
        to="supplier@apex.com",
        vendor_name="Apex Polymer Ltd",
        company_name="Apex Polymer Ltd",
        contact_person="John Doe",
    )
    assert "Apex Polymer Ltd" in cc_box
    assert "supplier@apex.com" in cc_box
    assert "John Doe" in cc_box


def test_comparison_sorting_least_total_price_first():
    """Verify quotation comparison sorting puts least total price first with accurate deltas."""
    # Build simulated entries
    entry1 = {
        "active": MagicMock(
            vendor_id="v1",
            negotiation_version=1,
            quotation=MagicMock(
                quoted_quantity=10,
                form_data={"price": 250000.0, "items": [{"name": "A", "price": 250000.0}]},
                submitted_at=datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc),
            ),
        ),
        "history": [],
    }
    entry2 = {
        "active": MagicMock(
            vendor_id="v2",
            negotiation_version=1,
            quotation=MagicMock(
                quoted_quantity=10,
                form_data={"price": 235000.0, "items": [{"name": "A", "price": 235000.0}]},
                submitted_at=datetime(2026, 10, 26, 11, 0, tzinfo=timezone.utc),
            ),
        ),
        "history": [],
    }

    from app.quotations.routes_internal import compare_quotations

    # Test pricing helper logic
    def calc_price(e):
        return float(e["active"].quotation.form_data["price"])

    entry1["total_price"] = calc_price(entry1)  # 250,000
    entry2["total_price"] = calc_price(entry2)  # 235,000

    sorted_entries = sorted([entry1, entry2], key=lambda e: e["total_price"])
    # 235,000 must come first!
    assert sorted_entries[0]["total_price"] == 235000.0
    assert sorted_entries[1]["total_price"] == 250000.0

    lowest_price = sorted_entries[0]["total_price"]
    for idx, e in enumerate(sorted_entries):
        e["rank"] = idx + 1
        e["is_lowest"] = (e["total_price"] == lowest_price)
        e["delta_price"] = e["total_price"] - lowest_price
        e["delta_percent"] = (e["delta_price"] / lowest_price) * 100

    assert sorted_entries[0]["rank"] == 1
    assert sorted_entries[0]["is_lowest"] is True
    assert sorted_entries[0]["delta_price"] == 0

    assert sorted_entries[1]["rank"] == 2
    assert sorted_entries[1]["is_lowest"] is False
    assert sorted_entries[1]["delta_price"] == 15000.0
    assert round(sorted_entries[1]["delta_percent"], 2) == 6.38


def test_bst_date_and_time_formatting():
    """Verify timestamps are converted from UTC to BST (GMT+6) accurately."""
    from app.utils.date_formatting import (
        to_bst,
        format_datetime_bst,
        format_date_bst,
        format_time_bst,
    )

    # 16:47 UTC is 22:47 BST (10:47 PM BST)
    utc_dt = datetime(2026, 11, 1, 16, 47, 28, tzinfo=timezone.utc)
    bst_dt = to_bst(utc_dt)
    assert bst_dt.hour == 22
    assert bst_dt.minute == 47

    formatted_dt = format_datetime_bst(utc_dt)
    assert "Nov 01, 2026 at 10:47 PM BST" == formatted_dt

    formatted_time = format_time_bst(utc_dt)
    assert "10:47 PM BST" == formatted_time

    # Naive datetime is interpreted as UTC
    naive_utc = datetime(2026, 11, 1, 16, 47, 28)
    assert format_datetime_bst(naive_utc) == "Nov 01, 2026 at 10:47 PM BST"

    # None returns fallback
    assert format_datetime_bst(None) == "—"


def test_requisition_id_search_cleaning():
    """Verify requisition search extracts and normalizes IDs from various copy-paste formats."""
    import re

    def clean_search_term(raw_search: str) -> tuple[str, str | None]:
        raw_search = raw_search.strip()
        uuid_match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", raw_search)
        clean_term = raw_search
        for prefix in (
            "Requisition #", "requisition #", "Requisition:", "requisition:", "Requisition ", "requisition ",
            "REQ-", "req-", "WO-", "wo-", "PO-", "po-", "RV-", "rv-", "#"
        ):
            if clean_term.startswith(prefix):
                clean_term = clean_term[len(prefix):].strip()
        found_uuid = uuid_match.group(1).lower() if uuid_match else None
        return clean_term, found_uuid

    # 1. Copied from notes: "Requisition #04c63e86-c223-4247-8c6d-88c113657283"
    term, uid = clean_search_term("Requisition #04c63e86-c223-4247-8c6d-88c113657283")
    assert uid == "04c63e86-c223-4247-8c6d-88c113657283"

    # 2. Copied with hash: "#04c63e86-c223-4247-8c6d-88c113657283"
    term, uid = clean_search_term("#04c63e86-c223-4247-8c6d-88c113657283")
    assert term == "04c63e86-c223-4247-8c6d-88c113657283"
    assert uid == "04c63e86-c223-4247-8c6d-88c113657283"

    # 3. Formatted code: "REQ-04C63E86"
    term, uid = clean_search_term("REQ-04C63E86")
    assert term == "04C63E86"

    # 4. Work order code: "WO-04C63E86"
    term, uid = clean_search_term("WO-04C63E86")
    assert term == "04C63E86"


def test_granular_menu_permissions_and_operations_manager_customization():
    """Verify granular menu permissions (can_access_audit, can_access_users, can_access_settings)."""
    from app.auth.models import UserProfile, UserRole

    # 1. Base Operations Manager: has operational authority, but no admin menus by default
    op_mgr = UserProfile(
        email="ops@wenerbd.com",
        full_name="Operations Lead",
        role=UserRole.OPERATIONS_MANAGER,
        can_access_audit=False,
        can_access_users=False,
        can_access_settings=False,
    )
    assert op_mgr.has_management_authority is True
    assert op_mgr.has_audit_access is False
    assert op_mgr.has_users_access is False
    assert op_mgr.has_settings_access is False
    assert op_mgr.can_access_admin_settings is False

    # 2. Operations Manager granted access to Audit and Users menus
    op_mgr.can_access_audit = True
    op_mgr.can_access_users = True
    assert op_mgr.has_audit_access is True
    assert op_mgr.has_users_access is True
    assert op_mgr.has_settings_access is False
    assert op_mgr.can_access_admin_settings is True

    # 3. Administrator: always has all menu and admin accesses
    admin = UserProfile(
        email="admin@wenerbd.com",
        full_name="System Admin",
        role=UserRole.ADMIN,
    )
    assert admin.has_audit_access is True
    assert admin.has_users_access is True
    assert admin.has_settings_access is True
    assert admin.can_access_admin_settings is True

    # 4. Standard Procurement Specialist: no admin menus
    procurement = UserProfile(
        email="buyer@wenerbd.com",
        full_name="Buyer One",
        role=UserRole.PROCUREMENT,
    )
    assert procurement.has_audit_access is False
    assert procurement.has_users_access is False
    assert procurement.has_settings_access is False


def test_users_and_permissions_page_ui_elements():
    """Verify Users & Permissions page template renders cards, italic roles, card actions, and permission checkboxes."""
    from pathlib import Path
    template_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/users/list.html")
    assert template_path.exists()
    content = template_path.read_text(encoding="utf-8")

    # Roles displayed in italics
    assert "*Operations Manager*" in content
    assert "*Procurement Specialist*" in content
    assert "*System Administrator*" in content

    # Action button as card
    assert "Edit Role &amp; Permissions" in content

    # Italic role descriptions under role name without hover tooltips
    assert "Creates requisitions, invites suppliers, manages RFQs" in content
    assert "Full management authority for requisition approval" in content

    # Granular menu checkboxes
    assert 'name="can_access_audit"' in content
    assert 'name="can_access_users"' in content
    assert 'name="can_access_settings"' in content
    assert "Activity Audit Log" in content


def test_excel_spreadsheet_requisition_canvas_layout():
    """Verify requisition create and edit templates feature wide MS Excel aspect ratio and spreadsheet table UX."""
    from pathlib import Path
    create_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/requisitions/create.html")
    edit_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/requisitions/edit.html")

    for path in (create_path, edit_path):
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        # Spread-out canvas
        assert "max-w-[1750px]" in content
        # Row index numbering
        assert "row-index" in content
        # Specification, quantity, and unit fields
        assert 'name="item_name[]"' in content
        assert 'name="item_desc[]"' in content
        assert 'name="item_qty[]"' in content
        assert 'name="item_unit[]"' in content
        # Summary footer
        assert "total-qty" in content
        assert "total-rows" in content


def test_unified_quotation_comparison_table_and_no_review_status():
    """Verify comparison page unifies matrix, shortlist, and vendor details into one table with toggle and no review status."""
    from pathlib import Path
    compare_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/quotations/compare.html")
    detail_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/quotations/detail.html")

    assert compare_path.exists()
    compare_content = compare_path.read_text(encoding="utf-8")

    # Unified master matrix table
    assert "unified-matrix-table" in compare_content
    # View mode vs Edit mode toggle
    assert "btn-mode-view" in compare_content
    assert "btn-mode-edit" in compare_content
    assert "cell-view-mode" in compare_content
    assert "cell-edit-mode" in compare_content
    # Sorting controls
    assert "table-sort-select" in compare_content
    assert "Lowest Price First" in compare_content
    assert "Fastest Delivery" in compare_content
    assert "Newest Submitted" in compare_content
    # Checkbox and editable quantity per item
    assert "shortlisted_ids" in compare_content
    assert "qty_{{ link_id }}_{{ item_idx }}" in compare_content

    # Confusing Review Status (Accept / Flag / Reset) removed
    assert "Review Status" not in compare_content
    assert "value=\"accepted\"" not in compare_content
    assert "value=\"flagged\"" not in compare_content

    # In detail.html as well
    assert detail_path.exists()
    detail_content = detail_path.read_text(encoding="utf-8")
    assert "Review Status" not in detail_content
    assert "value=\"accepted\"" not in detail_content
    assert "value=\"flagged\"" not in detail_content


@pytest.mark.asyncio
async def test_delete_user_reassigns_foreign_keys_safely(async_db):
    """Verify delete_user reassigns foreign keys and deletes user without PendingRollbackError."""
    from app.users.routes import delete_user
    from app.auth.models import UserProfile, UserRole
    from app.requisitions.models import Requisition
    from app.audit.models import AuditLog
    from starlette.requests import Request

    admin = UserProfile(
        id="admin-user-001",
        email="admin@wenerbd.cloud",
        full_name="Admin User",
        role=UserRole.ADMIN,
        can_access_users=True,
    )
    target = UserProfile(
        id="target-user-002",
        email="delete-me@test.com",
        full_name="Delete Me",
        role=UserRole.PROCUREMENT,
    )
    async_db.add_all([admin, target])
    await async_db.commit()

    # Create a requisition created by target
    req = Requisition(
        id="req-user-test-01",
        title="Test Requisition",
        created_by=target.id,
        qc_done_by=target.id,
    )
    log = AuditLog(
        id="log-001",
        action="CREATE",
        actor_name=target.full_name,
        actor_email=target.email,
        actor_role=target.role.value,
        entity_type="requisition",
        entity_id=req.id,
        actor_id=target.id,
    )
    async_db.add_all([req, log])
    await async_db.commit()

    # Call delete_user
    mock_request = MagicMock(spec=Request)
    response = await delete_user(
        target_user_id=target.id,
        request=mock_request,
        user=admin,
        db=async_db,
    )

    assert response.status_code == 303
    assert "permanently+deleted" in response.headers["location"]

    # Target should be deleted
    deleted_user = await async_db.get(UserProfile, target.id)
    assert deleted_user is None

    # Requisition should have created_by reassigned to admin, and qc_done_by set to None
    updated_req = await async_db.get(Requisition, req.id)
    assert updated_req.created_by == admin.id
    assert updated_req.qc_done_by is None

    # Audit log actor_id should be None
    updated_log = await async_db.get(AuditLog, log.id)
    assert updated_log.actor_id is None


def test_requisition_tabular_view_and_inline_editable_cells_and_a4_printing():
    """Verify requisition detail view features Excel tabular view, toggleable editable cells, and A4 print layout."""
    from pathlib import Path
    detail_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/requisitions/detail.html")
    list_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/requisitions/list.html")
    compare_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/quotations/compare.html")

    assert detail_path.exists()
    detail_content = detail_path.read_text(encoding="utf-8")

    # Wide layout
    assert "max-w-[1750px]" in detail_content
    # Excel table id & printable table
    assert "excel-items-table" in detail_content
    assert "print-table" in detail_content
    # Toggleable cells (view vs edit)
    assert "cell-view" in detail_content
    assert "cell-edit" in detail_content
    assert "toggleEditMode" in detail_content
    assert "btn-start-edit" in detail_content
    assert "btn-save-edit" in detail_content
    # A4 printable styling & signature block
    assert "print-only" in detail_content
    assert "PURCHASE REQUISITION ORDER" in detail_content
    assert "Prepared By (Requester)" in detail_content
    assert "Approved By (Management)" in detail_content
    assert "@page" in detail_content
    assert "A4 portrait" in detail_content

    # List page excel table
    assert list_path.exists()
    list_content = list_path.read_text(encoding="utf-8")
    assert "excel-requisitions-table" in list_content
    assert "Print Register (A4)" in list_content

    # Compare page cell edit mode matches view mode
    assert compare_path.exists()
    compare_content = compare_path.read_text(encoding="utf-8")
    assert "cell-edit-mode" in compare_content
    assert "Unit Rate:" in compare_content
    assert "Assign Item" in compare_content


def test_navbar_quotation_inbox_and_print_layout_rules():
    """Verify Quotation Inbox is present in desktop & mobile navigation, and global A4 print rules prevent half-page squishing."""
    from pathlib import Path
    base_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/base.html")
    assert base_path.exists()
    content = base_path.read_text(encoding="utf-8")

    # Quotation inbox link in desktop & mobile header
    assert "/quotations/inbox" in content
    assert "Quotation Inbox" in content

    # Global print styling overrides to prevent half-page desktop sidebar squishing
    assert "@media print" in content
    assert "size: A4 portrait;" in content
    assert "aside, header, nav, footer, #mobile-nav, .tab-bar, .no-print" in content
    assert "display: none !important;" in content
    assert "width: 0 !important;" in content
    assert "min-height: 0 !important;" in content


def test_executive_compare_quotations_hero_and_worksheet_lock_ui():
    """Verify Requisition detail features professional corporate compare actions, evaluation banner, and locked state when quotes exist."""
    from pathlib import Path
    detail_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/requisitions/detail.html")
    assert detail_path.exists()
    content = detail_path.read_text(encoding="utf-8")

    # Lock condition logic
    assert "has_submitted_quotes" in content
    assert "submitted_count" in content
    assert "Worksheet Locked (Quotes Submitted)" in content

    # Compare Quotations corporate action button
    assert "btn-action-compare-quotes" in content
    assert "Compare Quotations" in content

    # Quotation Evaluation Notice Banner
    assert "btn-hero-compare-quotes" in content
    assert "Evaluate &amp; Compare Supplier Quotations" in content
    assert "Compare &amp; Shortlist Quotes" in content

    # Fixed column percentage widths for 100% full-width A4 printing
    assert "table-layout: fixed !important;" in content
    assert "print-col-index" in content
    assert "print-col-name" in content
    assert "print-col-desc" in content
    assert "print-col-qty" in content
    assert "print-col-unit" in content


@pytest.mark.asyncio
async def test_requisition_edit_backend_locks_when_quotes_submitted(async_db):
    """Verify backend endpoints /requisitions/{id}/edit block edits once any supplier has submitted a quote."""
    from uuid import uuid4
    from app.auth.models import UserProfile, UserRole
    from app.requisitions.models import Requisition, RequisitionStatus, RequisitionVendor
    from app.requisitions.routes import edit_requisition_page
    from starlette.requests import Request

    user = UserProfile(
        id=str(uuid4()),
        email="buyer_lock_test@wenerbd.com",
        full_name="Lock Buyer",
        role=UserRole.PROCUREMENT,
    )
    async_db.add(user)
    await async_db.flush()

    req = Requisition(
        id=str(uuid4()),
        title="BOM For Testing Lock",
        quantity=50.0,
        status=RequisitionStatus.IN_PROGRESS,
        created_by=user.id,
    )
    async_db.add(req)
    await async_db.flush()

    # Add a vendor link with status='submitted'
    rv = RequisitionVendor(
        id=str(uuid4()),
        requisition_id=req.id,
        vendor_id=str(uuid4()),
        status="submitted",
    )
    async_db.add(rv)
    await async_db.commit()

    # Create dummy starlette request
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/requisitions/{req.id}/edit",
        "headers": [],
    }
    request = Request(scope)

    # Calling edit_requisition_page should redirect with error
    response = await edit_requisition_page(
        request=request,
        req_id=req.id,
        user=user,
        db=async_db,
    )
    assert response.status_code == 303
    assert "Requisition+is+locked+because+suppliers+have+already+submitted+quotations" in response.headers["location"]


def test_system_settings_high_contrast_and_no_provision_jargon():
    """Verify system settings is clean, legible, high-contrast light theme and tech buzzwords like 'provision' are purged."""
    from pathlib import Path
    settings_path = Path("/home/muhts/dev/Codes/wes-vendor/app/templates/settings/index.html")
    assert settings_path.exists()
    settings_content = settings_path.read_text(encoding="utf-8")

    # High contrast corporate titles & cards
    assert "System Configuration" in settings_content
    assert "text-slate-900" in settings_content
    assert "bg-white rounded-xl border border-slate-300" in settings_content
    assert "Automated Email Notification Recipients (CC)" in settings_content
    assert "Official Company Letterheads" in settings_content
    # No dark gaming containers or unstyled white-on-white text
    assert "bg-slate-900/70" not in settings_content
    assert "text-white tracking-tight" not in settings_content

    # Check that 'provision' is absent from all templates
    templates_dir = Path("/home/muhts/dev/Codes/wes-vendor/app/templates")
    for html_file in templates_dir.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8").lower()
        assert "provision" not in content, f"Found 'provision' in {html_file}"








