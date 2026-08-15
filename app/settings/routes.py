"""
Settings routes — management-only page to configure CC email addresses
that are automatically included in all outbound Resend emails.
"""
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_role
from app.settings.models import SystemSettings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

_MANAGEMENT_ROLES = ("management", "admin")


@router.get("")
async def settings_page(
    request: Request,
    user: CurrentUser = Depends(require_role(*_MANAGEMENT_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    cc_row = await db.get(SystemSettings, SystemSettings.cc_emails_key())
    cc_emails: list[str] = cc_row.get_list() if cc_row else []

    return templates.TemplateResponse(
        request,
        "settings/index.html",
        {
            "user": user,
            "cc_emails": cc_emails,
            "saved": request.query_params.get("saved"),
        },
    )


@router.post("/cc-emails/add")
async def add_cc_email(
    request: Request,
    email: str = Form(...),
    user: CurrentUser = Depends(require_role(*_MANAGEMENT_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    if not email or "@" not in email:
        return RedirectResponse("/settings?error=invalid_email", status_code=303)

    cc_row = await db.get(SystemSettings, SystemSettings.cc_emails_key())
    if cc_row is None:
        cc_row = SystemSettings(key=SystemSettings.cc_emails_key(), value="[]")
        db.add(cc_row)

    emails = cc_row.get_list()
    if email not in emails:
        emails.append(email)
        cc_row.value = SystemSettings.encode_list(emails)

    await db.commit()
    logger.info("CC email added by %s: %s", user.email, email)
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/cc-emails/remove")
async def remove_cc_email(
    request: Request,
    email: str = Form(...),
    user: CurrentUser = Depends(require_role(*_MANAGEMENT_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    email = email.strip().lower()
    cc_row = await db.get(SystemSettings, SystemSettings.cc_emails_key())
    if cc_row:
        emails = [e for e in cc_row.get_list() if e != email]
        cc_row.value = SystemSettings.encode_list(emails)
        await db.commit()
        logger.info("CC email removed by %s: %s", user.email, email)

    return RedirectResponse("/settings?saved=1", status_code=303)
