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


# ──────────────────────────────────────────────────────────────────────────────
# Email builders — all pull CC from DB via get_cc_emails()
# ──────────────────────────────────────────────────────────────────────────────

async def build_vendor_invitation(
    to: str, vendor_name: str, requisition_title: str, quote_url: str
) -> dict:
    cc = await get_cc_emails()
    html = f"""
    <h2>You have a new quotation request</h2>
    <p>Dear {vendor_name},</p>
    <p>You have been invited to submit a quotation for: <strong>{requisition_title}</strong></p>
    <p><a href="{quote_url}">Click here to submit your quotation</a></p>
    <p>If you have any questions, please contact us directly.</p>
    """
    return _apply_cc({
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Request: {requisition_title}",
        "html": html,
    }, cc)


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
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": subject,
        "html": body,
    }, cc)


async def build_submission_notification(
    to: str, vendor_name: str, requisition_title: str, view_url: str
) -> dict:
    cc = await get_cc_emails()
    html = f"""
    <h2>Quotation Submitted</h2>
    <p>Vendor <strong>{vendor_name}</strong> has submitted a quotation for your requisition: <strong>{requisition_title}</strong>.</p>
    <p><a href="{view_url}">Click here to view the quotation details in the portal</a></p>
    """
    return _apply_cc({
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Submitted: {vendor_name} - {requisition_title}",
        "html": html,
    }, cc)


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
        "from": f"Vendor Portal <{settings.mail_from}>",
        "to": [to],
        "subject": f"Quotation Received: {requisition_title}",
        "html": html,
    }, cc)
