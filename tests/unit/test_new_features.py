import pytest
from app.reports.pdf_service import generate_rfq_pdf
from app.email.resend import (
    build_submission_confirmation,
    build_submission_notification,
    build_vendor_invitation,
)
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
