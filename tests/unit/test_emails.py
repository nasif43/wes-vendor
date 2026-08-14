from app.config import get_settings
from app.email.resend import (
    build_vendor_invitation,
    build_decision_notification,
    build_submission_notification,
    build_submission_confirmation,
)

def test_email_payloads_with_default_cc():
    settings = get_settings()
    original_cc = settings.default_cc
    try:
        # Set a default CC email
        settings.default_cc = "test_cc@example.com"
        
        invitation = build_vendor_invitation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            quote_url="http://example.com/quote",
        )
        assert invitation["cc"] == ["test_cc@example.com"]
        
        decision = build_decision_notification(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            approved=True,
        )
        assert decision["cc"] == ["test_cc@example.com"]
        
        submission_notif = build_submission_notification(
            to="creator@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            view_url="http://example.com/view",
        )
        assert submission_notif["cc"] == ["test_cc@example.com"]
        
        submission_conf = build_submission_confirmation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
        )
        assert submission_conf["cc"] == ["test_cc@example.com"]
        
    finally:
        settings.default_cc = original_cc


def test_email_payloads_without_default_cc():
    settings = get_settings()
    original_cc = settings.default_cc
    try:
        # Clear default CC email
        settings.default_cc = ""
        
        invitation = build_vendor_invitation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            quote_url="http://example.com/quote",
        )
        assert "cc" not in invitation
        
        decision = build_decision_notification(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            approved=True,
        )
        assert "cc" not in decision
        
        submission_notif = build_submission_notification(
            to="creator@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
            view_url="http://example.com/view",
        )
        assert "cc" not in submission_notif
        
        submission_conf = build_submission_confirmation(
            to="vendor@example.com",
            vendor_name="Vendor A",
            requisition_title="Req A",
        )
        assert "cc" not in submission_conf
        
    finally:
        settings.default_cc = original_cc
