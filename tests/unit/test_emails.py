import pytest
from unittest.mock import patch
from app.config import get_settings
from app.email.resend import (
    build_vendor_invitation,
    build_decision_notification,
    build_submission_notification,
    build_submission_confirmation,
    invalidate_cc_cache,
)

@pytest.mark.anyio
async def test_email_payloads_with_default_cc():
    with patch("app.email.resend.get_cc_emails", return_value=["test_cc@example.com"]):
        invitation = await build_vendor_invitation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            quote_url="http://example.com/quote",
        )
        assert invitation["cc"] == ["test_cc@example.com"]
        
        decision = await build_decision_notification(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            approved=True,
        )
        assert decision["cc"] == ["test_cc@example.com"]
        
        submission_notif = await build_submission_notification(
            to="creator@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            view_url="http://example.com/view",
        )
        assert submission_notif[0]["cc"] == ["test_cc@example.com"]
        
        submission_conf = await build_submission_confirmation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            pdf_bytes=b"%PDF-1.4 test",
        )
        assert submission_conf["cc"] == ["test_cc@example.com"]
        assert len(submission_conf["attachments"]) == 1

@pytest.mark.anyio
async def test_email_payloads_without_default_cc():
    with patch("app.email.resend.get_cc_emails", return_value=[]):
        invitation = await build_vendor_invitation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            quote_url="http://example.com/quote",
        )
        assert "cc" not in invitation
        
        decision = await build_decision_notification(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            approved=True,
        )
        assert "cc" not in decision
        
        submission_notif = await build_submission_notification(
            to="creator@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            view_url="http://example.com/view",
        )
        assert "cc" not in submission_notif[0]
        
        submission_conf = await build_submission_confirmation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
        )
        assert "cc" not in submission_conf


@pytest.mark.anyio
async def test_mail_from_uses_wenerbd_cloud():
    invitation = await build_vendor_invitation(
        to="vendor@example.com",
        vendor_name="Vendor A",
        requisition_title="Req A",
        quote_url="http://example.com/quote",
    )
    assert "@wenerbd.cloud" in invitation["from"]
    assert "coolcompany.tech" not in invitation["from"]


@pytest.mark.anyio
async def test_send_batch_sanitizes_legacy_domain():
    from app.email.resend import send_batch

    sent_payloads = []
    with patch("resend.Emails.send", side_effect=lambda p: (sent_payloads.append(p), {"id": "mock_id"})[1]):
        payload = {
            "from": "Wener Supplier Management <portal@coolcompany.tech>",
            "to": ["test@example.com"],
            "subject": "Test",
            "html": "<p>Hello</p>",
        }
        res = await send_batch([payload])
        assert res is True
        assert len(sent_payloads) == 1
        assert "portal@wenerbd.cloud" in sent_payloads[0]["from"]
        assert "coolcompany.tech" not in sent_payloads[0]["from"]

