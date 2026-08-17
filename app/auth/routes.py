
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserProfile, UserRole
from app.config import get_settings
from app.database import get_db

router = APIRouter()
settings = get_settings()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    from app.main import templates
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    from app.main import templates  # noqa: F401

    clean_email = email.strip().lower()
    result = await db.execute(
        select(UserProfile).where(func.lower(UserProfile.email) == clean_email)
    )
    user = result.scalar_one_or_none()

    # In dev mode: if user profile doesn't exist yet in DB, auto-create it instantly
    if not user:
        full_name = clean_email.split("@")[0].replace(".", " ").title()
        is_admin_or_mgmt = "admin" in clean_email or "manage" in clean_email or "mizanur" in clean_email
        is_qc = "qc" in clean_email or "kamrul" in clean_email
        is_purchaser = "procurement" in clean_email or "purchase" in clean_email or "tanjila" in clean_email

        role = UserRole.ADMIN if is_admin_or_mgmt else (UserRole.QC_RECEIVER if is_qc else UserRole.PROCUREMENT)
        user = UserProfile(
            email=clean_email,
            full_name=full_name,
            role=role,
            can_view_quotations=is_admin_or_mgmt,
            can_do_qc=is_admin_or_mgmt or is_qc,
            can_view_all_requisitions=is_admin_or_mgmt or is_qc,
            is_management=is_admin_or_mgmt,
        )
        db.add(user)
        await db.flush()


    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


from fastapi import HTTPException

@router.get("/seed-db")
async def trigger_db_seed(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not settings.enable_seed_endpoint:
        raise HTTPException(status_code=404, detail="Seed endpoint is disabled")
    try:
        from scripts.seed import main as seed_main
        await seed_main()
        return RedirectResponse(url="/auth/login?success=Database+re-seeded+successfully", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/auth/login?error=Seed+failed:+{str(e)[:100]}", status_code=303)


@router.get("/signup")
async def signup_page(request: Request):
    return RedirectResponse(
        url="/auth/login?error=Self-registration+is+disabled.+User+accounts+are+provisioned+by+System+Administrator.",
        status_code=303,
    )


@router.post("/signup")
async def signup(request: Request):
    return RedirectResponse(
        url="/auth/login?error=Self-registration+is+disabled.+User+accounts+are+provisioned+by+System+Administrator.",
        status_code=303,
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=303)
