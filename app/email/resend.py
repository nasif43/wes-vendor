"""
Email helpers using the Resend Python SDK.

CC recipients are fetched from the system_settings DB table (key='cc_emails')
so management can configure them via /settings without a redeploy.
The DEFAULT_CC env var is only used as a seed fallback if no DB row exists yet.

Resend API reference: https://resend.com/docs/api-reference/emails/send-email
  - `cc` accepts a list of email strings
  - `to` accepts a list of email strings
  - `from` must be a verified sending address
"""
import asyncio
import logging

import resend

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

if settings.resend_api_key:
    resend.api_key = settings.resend_api_key


import time

_cc_cache: list[str] | None = None
_cc_cache_ts: float = 0.0
_CC_TTL: float = 300.0  # cache for 5 minutes


def invalidate_cc_cache() -> None:
    global _cc_cache, _cc_cache_ts
    _cc_cache = None
    _cc_cache_ts = 0.0


def _seed_from_env() -> list[str]:
    env_cc = settings.default_cc.strip() if settings.default_cc else ""
    return [e.strip() for e in env_cc.split(",") if e.strip()] if env_cc else []


# ──────────────────────────────────────────────────────────────────────────────
# CC helpers
# ──────────────────────────────────────────────────────────────────────────────

async def get_cc_emails() -> list[str]:
    """
    Return the current CC list from the DB with in-memory TTL caching.
    Falls back to DEFAULT_CC env var if no DB row exists yet.
    Never raises — returns [] on any error.
    """
    global _cc_cache, _cc_cache_ts
    now = time.monotonic()
    if _cc_cache is not None and (now - _cc_cache_ts) < _CC_TTL:
        return _cc_cache

    try:
        from app.database import AsyncSessionLocal
        from app.settings.models import SystemSettings

        async with AsyncSessionLocal() as db:
            row = await db.get(SystemSettings, SystemSettings.cc_emails_key())
            if row is not None:
                _cc_cache = row.get_list()
                _cc_cache_ts = now
                return _cc_cache

            # No DB row yet — seed from env var and persist
            seeded = _seed_from_env()
            if seeded:
                new_row = SystemSettings(
                    key=SystemSettings.cc_emails_key(),
                    value=SystemSettings.encode_list(seeded),
                )
                db.add(new_row)
                await db.commit()
                logger.info("Seeded CC emails from env: %s", seeded)
            _cc_cache = seeded
            _cc_cache_ts = now
            return _cc_cache
    except Exception as exc:
        logger.warning("Could not load CC emails from DB: %s", exc)
        if _cc_cache is not None:
            return _cc_cache
        return _seed_from_env()


def _apply_cc(payload: dict, cc: list[str]) -> dict:
    """Attach cc field to a Resend email payload if the list is non-empty."""
    if cc:
        payload["cc"] = cc
    return payload


# ──────────────────────────────────────────────────────────────────────────────
# Batch sender
# ──────────────────────────────────────────────────────────────────────────────

async def send_batch(params: list[dict]) -> bool:
    if not settings.resend_api_key or settings.resend_api_key == "re_xxxxxxxxx":
        logger.warning("Resend API key not configured — skipping %d email(s)", len(params))
        import os, uuid
        os.makedirs("local_emails", exist_ok=True)
        for p in params:
            email_id = str(uuid.uuid4())[:8]
            html_content = p.get("html", "")
            with open(f"local_emails/{email_id}.html", "w") as f_out:
                f_out.write(html_content)
            logger.info("--> Saved mock email to local_emails/%s.html", email_id)
        return False
    if not params:
        return False

    async def _send_async(p):
        def _send():
            return resend.Emails.send(p)
        try:
            result = await asyncio.to_thread(_send)
            return "id" in result
        except Exception as e:
            logger.error("Failed to send email: %s", e)
            return False

    # Execute all email requests concurrently to prevent hindering the user's workflow
    results = await asyncio.gather(*[_send_async(p) for p in params])
    success = all(results)
    
    if success:
        logger.info("Sent %d email(s) concurrently using Emails.send", len(params))
    return success

# ──────────────────────────────────────────────────────────────────────────────
# Email builders — all pull CC from DB via get_cc_emails()
# ──────────────────────────────────────────────────────────────────────────────

async def build_vendor_invitation(
    to: str, vendor_name: str, requisition_title: str, quote_url: str, pdf_bytes: bytes | None = None
) -> dict:
    cc = await get_cc_emails()
    html = f"""
    <h2>Quotation Request</h2>
    <p>Dear {vendor_name},</p>
    <p>You have been invited to submit a quotation for: <strong>{requisition_title}</strong>.</p>
    <p>Please review the attached Request for Quotation (RFQ) document.</p>
    <p><a href="{quote_url}">Click here to submit your quotation online</a></p>
    <p>This link is unique to you. Do not share it.</p>
    """
    payload = {
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Request: {requisition_title}",
        "html": html,
    }
    if pdf_bytes:
        payload["attachments"] = [{"filename": f"RFQ_{requisition_title.replace(' ', '_')}.pdf", "content": list(pdf_bytes), "content_type": "application/pdf"}]
    return _apply_cc(payload, cc)


async def build_decision_notification(
    to: str, vendor_name: str, requisition_title: str, approved: bool | None
) -> dict | None:
    if approved is True:
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

    cc = await get_cc_emails()
    return _apply_cc({
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": subject,
        "html": body,
    }, cc)


async def build_submission_notification(
    to: str, vendor_name: str, requisition_title: str, view_url: str, pdf_bytes: bytes | None = None
) -> dict:
    cc = await get_cc_emails()
    html = f"""
    <h2>Quotation Submitted</h2>
    <p>Supplier <strong>{vendor_name}</strong> has submitted a quotation for your requisition: <strong>{requisition_title}</strong>.</p>
    <p><a href="{view_url}">Click here to view the quotation details in the portal</a></p>
    """
    payload = {
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"{requisition_title} - {vendor_name}",
        "html": html,
    }
    if pdf_bytes:
        payload["attachments"] = [{"filename": f"Quotation_{vendor_name}.pdf", "content": list(pdf_bytes), "content_type": "application/pdf"}]
    return _apply_cc(payload, cc)


async def build_submission_confirmation(
    to: str, vendor_name: str, requisition_title: str
) -> dict:
    cc = await get_cc_emails()
    html = f"""
    <h2>Quotation Received</h2>
    <p>Dear {vendor_name},</p>
    <p>Thank you for submitting your quotation for <strong>{requisition_title}</strong>. We have received it successfully and will review it shortly.</p>
    """
    return _apply_cc({
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Received: {requisition_title}",
        "html": html,
    }, cc)


async def build_work_order_email(
    to: str,
    supplier_name: str,
    requisition_title: str,
    pdf_bytes: bytes,
    work_order_ref: str = "",
) -> dict:
    """Work order email with PDF attachment sent to winning supplier + management CC."""
    cc = await get_cc_emails()
    html = f"""
    <h2>Work Order Issued</h2>
    <p>Dear {supplier_name},</p>
    <p>Please find attached the official Work Order / Purchase Order for
    <strong>{requisition_title}</strong>.</p>
    <p>Kindly proceed with the delivery of the requested items as per the agreed
    specifications and timeline.</p>
    {f'<p>Work Order Reference: <strong>{work_order_ref}</strong></p>' if work_order_ref else ''}
    <p>If you have any questions regarding this order, please contact us directly.</p>
    """
    payload = {
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Work Order: {requisition_title}",
        "html": html,
        "attachments": [{
            "filename": f"WorkOrder_{work_order_ref or 'ref'}.pdf",
            "content": list(pdf_bytes),
        }],
    }
    return _apply_cc(payload, cc)


async def build_invoice_email(
    to: str,
    supplier_name: str,
    requisition_title: str,
    invoice_number: str,
    grand_total: float,
    pdf_bytes: bytes,
) -> dict:
    """Invoice email with PDF attachment sent to management CC on invoice finalization."""
    cc = await get_cc_emails()
    html = f"""
    <h2>Invoice Generated</h2>
    <p>The invoice for requisition <strong>{requisition_title}</strong> has been
    generated and finalized.</p>
    <table style="font-family: sans-serif; font-size: 14px; width: 100%; max-width: 400px; margin: 16px 0;">
      <tr><td style="padding: 4px 0; color: #666;">Supplier:</td>
          <td style="padding: 4px 0; font-weight: 600;">{supplier_name}</td></tr>
      <tr><td style="padding: 4px 0; color: #666;">Invoice No:</td>
          <td style="padding: 4px 0; font-weight: 600;">{invoice_number}</td></tr>
      <tr><td style="padding: 4px 0; color: #666;">Total Payable:</td>
          <td style="padding: 4px 0; font-weight: 700; font-size: 16px;">৳{grand_total:.2f}</td></tr>
    </table>
    <p style="font-size: 12px; color: #888;">This invoice reflects accepted quantities only.
    Rejected items have been excluded from the total.</p>
    """
    payload = {
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Invoice #{invoice_number} — {requisition_title} (৳{grand_total:.2f})",
        "html": html,
        "attachments": [{
            "filename": f"Invoice_{invoice_number}.pdf",
            "content": list(pdf_bytes),
        }],
    }
    return _apply_cc(payload, cc)


async def build_negotiation_invitation(
    to: str,
    supplier_name: str,
    requisition_title: str,
    quote_url: str,
    pdf_bytes: bytes | None = None
) -> dict:
    """v2 negotiation invitation — clearly labeled as a revision request.
    
    Sent to shortlisted suppliers when management starts the negotiation round.
    """
    cc = await get_cc_emails()
    html = f"""
    <h2>Revised Quotation Request (Round 2)</h2>
    <p>Dear {supplier_name},</p>
    <p>You have been shortlisted for the next round of evaluation for:
    <strong>{requisition_title}</strong>.</p>
    <p>We invite you to submit a <strong>revised quotation</strong> for the specific
    items allocated to you. Please review the attached Request for Quotation (RFQ) document.</p>
    <p><a href="{quote_url}" style="display:inline-block;background:#1d4ed8;color:white;
    padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600;
    margin:20px 0;">Submit Revised Quotation</a></p>
    <p>This link is unique to you. Do not share it.</p>
    <hr>
    <p style="font-size: 12px; color: #666;">This is an automated system notification.</p>
    """
    payload = {
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Revised Quotation Request (Round 2): {requisition_title}",
        "html": html,
    }
    if pdf_bytes:
        payload["attachments"] = [{"filename": f"Revised_RFQ_{requisition_title.replace(' ', '_')}.pdf", "content": list(pdf_bytes), "content_type": "application/pdf"}]
    return _apply_cc(payload, cc)


async def build_rejection_notification(
    to: str,
    supplier_name: str,
    requisition_title: str,
) -> dict:
    """Rejection notification sent to non-shortlisted suppliers after negotiation starts."""
    cc = await get_cc_emails()
    html = f"""
    <h2>Update on Your Quotation</h2>
    <p>Dear {supplier_name},</p>
    <p>Thank you for your quotation for <strong>{requisition_title}</strong>.</p>
    <p>After careful evaluation, we regret to inform you that we will not be
    proceeding with your quotation for this particular requisition.</p>
    <p>We appreciate your participation and hope to work with you on future
    opportunities.</p>
    """
    return _apply_cc({
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Update on Your Quotation: {requisition_title}",
        "html": html,
    }, cc)


async def build_award_notification(
    to: str,
    supplier_name: str,
    requisition_title: str,
) -> dict:
    """Award notification sent to winning supplier when management selects them.
    
    Informs the winner that they've been selected and to expect a Work Order.
    """
    cc = await get_cc_emails()
    html = f"""
    <h2>Congratulations! Your Quotation Has Been Accepted</h2>
    <p>Dear {supplier_name},</p>
    <p>We are pleased to inform you that your quotation for
    <strong>{requisition_title}</strong> has been accepted.</p>
    <p>You will shortly receive an official <strong>Work Order / Purchase Order</strong>
    with the full details of the items to be supplied.</p>
    <p>Please be prepared to proceed with delivery upon receiving the Work Order.</p>
    """
    return _apply_cc({
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Award Notification: {requisition_title}",
        "html": html,
    }, cc)


# ──────────────────────────────────────────────────────────────────────────────
# Resend Health & Quota Checker
# ──────────────────────────────────────────────────────────────────────────────

async def get_resend_health_data() -> dict:
    """
    Query the Resend API dynamically to compute live quota usage and health metrics.
    Free tier limits: 100 emails/day, 3,000 emails/month.
    """
    import httpx
    from datetime import datetime, timezone

    MONTHLY_LIMIT = 3000
    DAILY_LIMIT = 100

    api_key = settings.resend_api_key
    if not api_key or api_key == "re_xxxxxxxxx":
        return {
            "status": "unconfigured",
            "error": "Resend API key is not configured.",
            "monthly_limit": MONTHLY_LIMIT,
            "daily_limit": DAILY_LIMIT,
            "monthly_used": 0,
            "monthly_remaining": MONTHLY_LIMIT,
            "daily_used": 0,
            "daily_remaining": DAILY_LIMIT,
            "monthly_pct": 0,
            "daily_pct": 0,
            "recent_emails": [],
            "domains": [],
            "rate_limit": None,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "wes-vendor-portal",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            emails_resp, domains_resp = await asyncio.gather(
                client.get("https://api.resend.com/emails", headers=headers),
                client.get("https://api.resend.com/domains", headers=headers),
                return_exceptions=True,
            )

        if isinstance(emails_resp, Exception):
            raise emails_resp
        if emails_resp.status_code != 200:
            return {
                "status": "error",
                "error": f"Resend API error ({emails_resp.status_code}): {emails_resp.text}",
                "monthly_limit": MONTHLY_LIMIT,
                "daily_limit": DAILY_LIMIT,
                "monthly_used": 0,
                "monthly_remaining": MONTHLY_LIMIT,
                "daily_used": 0,
                "daily_remaining": DAILY_LIMIT,
            "monthly_pct": 0,
            "daily_pct": 0,
                "recent_emails": [],
                "domains": [],
                "rate_limit": None,
                "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            }

        emails_data = emails_resp.json().get("data", [])
        domains_data = []
        if not isinstance(domains_resp, Exception) and domains_resp.status_code == 200:
            domains_data = domains_resp.json().get("data", [])

        now = datetime.now(timezone.utc)
        current_month_str = now.strftime("%Y-%m")
        today_str = now.strftime("%Y-%m-%d")

        monthly_used = 0
        daily_used = 0

        for e in emails_data:
            created_at = e.get("created_at", "")
            if created_at.startswith(current_month_str):
                monthly_used += 1
            if created_at.startswith(today_str):
                daily_used += 1

        monthly_remaining = max(0, MONTHLY_LIMIT - monthly_used)
        daily_remaining = max(0, DAILY_LIMIT - daily_used)

        rate_limit = {
            "limit": emails_resp.headers.get("ratelimit-limit"),
            "remaining": emails_resp.headers.get("ratelimit-remaining"),
            "reset": emails_resp.headers.get("ratelimit-reset"),
        }

        return {
            "status": "healthy",
            "error": None,
            "monthly_limit": MONTHLY_LIMIT,
            "daily_limit": DAILY_LIMIT,
            "monthly_used": monthly_used,
            "monthly_remaining": monthly_remaining,
            "monthly_pct": round((monthly_used / MONTHLY_LIMIT) * 100, 2),
            "daily_used": daily_used,
            "daily_remaining": daily_remaining,
            "daily_pct": round((daily_used / DAILY_LIMIT) * 100, 2),
            "recent_emails": emails_data[:20],
            "domains": domains_data,
            "rate_limit": rate_limit,
            "checked_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
    except Exception as exc:
        logger.exception("Failed to fetch Resend health: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "monthly_limit": MONTHLY_LIMIT,
            "daily_limit": DAILY_LIMIT,
            "monthly_used": 0,
            "monthly_remaining": MONTHLY_LIMIT,
            "daily_used": 0,
            "daily_remaining": DAILY_LIMIT,
            "monthly_pct": 0,
            "daily_pct": 0,
            "recent_emails": [],
            "domains": [],
            "rate_limit": None,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }


async def build_cancellation_notification(
    to: str, supplier_name: str, requisition_title: str
) -> dict:
    cc = await get_cc_emails()
    html = f'''
    <h2>Update: Quotation Request Cancelled</h2>
    <p>Dear {supplier_name},</p>
    <p>This is to inform you that the Request for Quotation (RFQ) for <strong>{requisition_title}</strong> has been cancelled by our management team.</p>
    <p>If you were preparing a quotation for this request, please do not submit it, as the submission link has been deactivated.</p>
    <p>We apologize for any inconvenience this may cause and look forward to working with you on future opportunities.</p>
    '''
    return _apply_cc({
        "from": f"Wener Supplier Management <{settings.mail_from}>",
        "to": [to],
        "subject": f"Update: RFQ Cancelled - {requisition_title}",
        "html": html,
    }, cc)
