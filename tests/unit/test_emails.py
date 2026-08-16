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
        assert submission_notif["cc"] == ["test_cc@example.com"]
        
        submission_conf = await build_submission_confirmation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
        )
        assert submission_conf["cc"] == ["test_cc@example.com"]


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
        assert "cc" not in submission_notif
        
        submission_conf = await build_submission_confirmation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
        )
        assert "cc" not in submission_conf
