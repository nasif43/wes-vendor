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
