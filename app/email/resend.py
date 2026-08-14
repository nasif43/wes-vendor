import asyncio
import logging

import resend

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

if settings.resend_api_key:
    resend.api_key = settings.resend_api_key


async def send_batch(params: list[dict]) -> bool:
    if not settings.resend_api_key or settings.resend_api_key == "re_xxxxxxxxx":
        logger.warning("Resend API key not configured — skipping %d email(s)", len(params))
        return False
    if not params:
        return False

    def _send() -> dict:
        return resend.Batch.send(params)

    try:
        result = await asyncio.to_thread(_send)
        if "data" in result:
            logger.info("Batch email sent: %d message(s)", len(params))
            return True
        logger.error("Batch send returned unexpected response: %s", result)
        return False
    except Exception as e:
        logger.error("Batch email failed: %s", e)
        return False


def build_vendor_invitation(
    to: str, vendor_name: str, requisition_title: str, quote_url: str
) -> dict:
    html = f"""
    <h2>You have a new quotation request</h2>
    <p>Dear {vendor_name},</p>
    <p>You have been invited to submit a quotation for: <strong>{requisition_title}</strong></p>
    <p><a href="{quote_url}">Click here to submit your quotation</a></p>
    <p>If you have any questions, please contact us directly.</p>
    """
    payload = {
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Request: {requisition_title}",
        "html": html,
    }
    if settings.default_cc:
        payload["cc"] = [settings.default_cc]
    return payload


def build_decision_notification(
    to: str, vendor_name: str, requisition_title: str, approved: bool | None
) -> dict | None:
    if approved:
        subject = f"Congratulations! Your quote for {requisition_title} was accepted"
        body = (
            f"Dear {vendor_name},<p>Your quotation for "
            f"<strong>{requisition_title}</strong> has been accepted. "
            f"We will be in touch shortly with next steps.</p>"
        )
    elif approved is False:
        subject = f"Update on your quote for {requisition_title}"
        body = (
            f"Dear {vendor_name},<p>Thank you for your quotation for "
            f"<strong>{requisition_title}</strong>. Unfortunately, "
            f"we have decided to go with another vendor this time.</p>"
        )
    else:
        return None

    payload = {
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": subject,
        "html": body,
    }
    if settings.default_cc:
        payload["cc"] = [settings.default_cc]
    return payload


def build_submission_notification(
    to: str, vendor_name: str, requisition_title: str, view_url: str
) -> dict:
    html = f"""
    <h2>Quotation Submitted</h2>
    <p>Vendor <strong>{vendor_name}</strong> has submitted a quotation for your requisition: <strong>{requisition_title}</strong>.</p>
    <p><a href="{view_url}">Click here to view the quotation details in the portal</a></p>
    """
    payload = {
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Submitted: {vendor_name} - {requisition_title}",
        "html": html,
    }
    if settings.default_cc:
        payload["cc"] = [settings.default_cc]
    return payload


def build_submission_confirmation(
    to: str, vendor_name: str, requisition_title: str
) -> dict:
    html = f"""
    <h2>Quotation Received</h2>
    <p>Dear {vendor_name},</p>
    <p>Thank you for submitting your quotation for <strong>{requisition_title}</strong>. We have received it successfully and will review it shortly.</p>
    """
    payload = {
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Received: {requisition_title}",
        "html": html,
    }
    if settings.default_cc:
        payload["cc"] = [settings.default_cc]
    return payload
