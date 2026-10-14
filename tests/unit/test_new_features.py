import pytest
from app.reports.pdf_service import generate_rfq_pdf
from app.email.resend import (
    build_submission_confirmation,
    build_submission_notification,
    build_vendor_invitation,
)
from app.auth.models import UserProfile, UserRole
from app.vendors.models import Vendor
from app.quotations.models import Quotation
from app.requisitions.models import Requisition

@pytest.mark.anyio
async def test_generate_rfq_pdf_with_issuer():
    class DummyReq:
        title = "Office Laptop Procurement"
    req = DummyReq()
    items = [{"name": "Laptop", "description": "16GB RAM", "qty": 5}]
    pdf = generate_rfq_pdf(
        req, "Acme Tech", items, issuer_name="Muhtasim Admin"
    )
    assert pdf is not None
    assert pdf.startswith(b"%PDF-")

@pytest.mark.anyio
async def test_submission_confirmation_with_pdf():
    pdf_bytes = b"%PDF-1.4 mock quotation pdf content"
    conf = await build_submission_confirmation(
        to="supplier@example.com",
        vendor_name="Acme Tech",
        requisition_title="Office Furniture",
        pdf_bytes=pdf_bytes,
    )
    assert conf["to"] == ["supplier@example.com"]
    assert "attachments" in conf
    assert len(conf["attachments"]) == 1
    assert conf["attachments"][0]["filename"] == "Quotation_Submitted_Office_Furniture.pdf"
    assert bytes(conf["attachments"][0]["content"]) == pdf_bytes

@pytest.mark.anyio
async def test_vendor_invitation_with_pdf():
    pdf_bytes = b"%PDF-1.4 mock rfq pdf"
    invite = await build_vendor_invitation(
        to="supplier@example.com",
        vendor_name="Acme Tech",
        requisition_title="Test Tender",
        quote_url="https://portal.example.com/vendor-quote/testtoken",
        pdf_bytes=pdf_bytes,
    )
    assert "attachments" in invite
    assert invite["attachments"][0]["filename"] == "RFQ_Test_Tender.pdf"


@pytest.mark.anyio
async def test_user_rename_reflects_in_issuer_and_pdf():
    from app.auth.models import UserProfile, UserRole

    user = UserProfile(
        email="procurement_test@wenerbd.com",
        username="proc1",
        full_name="Procurement",
        role=UserRole.PROCUREMENT,
    )
    assert (user.full_name or user.username) == "Procurement"

    # Sysadmin renames user to actual human name
    user.full_name = "Md. Rafiqul Islam"
    assert (user.full_name or user.username) == "Md. Rafiqul Islam"

    class DummyReq:
        title = "Office Supplies Requisition"

    pdf = generate_rfq_pdf(
        DummyReq(),
        supplier_name="Bengal Traders",
        items=[{"name": "A4 Paper", "qty": 10}],
        issuer_name=user.full_name or user.username,
    )
    assert pdf is not None
    assert pdf.startswith(b"%PDF-")


def test_procurement_ownership_and_blind_permissions():
    from app.auth.models import UserProfile, UserRole

    # Standard procurement officer with no extra permissions
    proc1 = UserProfile(
        id="user-1",
        email="officer1@example.com",
        full_name="Officer 1",
        role=UserRole.PROCUREMENT,
        can_view_all_requisitions=False,
        can_view_quotations=False,
        is_management=False,
    )
    assert proc1.can_see_all_requisitions is False
    assert proc1.can_see_quotes is False
    assert proc1.is_procurement_blind is True

    # Procurement officer with "See All"
    proc2 = UserProfile(
        id="user-2",
        email="officer2@example.com",
        full_name="Officer 2",
        role=UserRole.PROCUREMENT,
        can_view_all_requisitions=True,
        can_view_quotations=False,
        is_management=False,
    )
    assert proc2.can_see_all_requisitions is True
    assert proc2.can_see_quotes is False
    assert proc2.is_procurement_blind is True

    # Management user has full visibility and price access
    mgmt = UserProfile(
        id="user-3",
        email="mgmt@example.com",
        full_name="Management",
        role=UserRole.MANAGEMENT,
    )
    assert mgmt.can_see_all_requisitions is True
    assert mgmt.can_see_quotes is True
    assert mgmt.is_procurement_blind is False


