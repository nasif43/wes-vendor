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


