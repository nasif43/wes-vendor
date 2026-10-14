
from fastapi import APIRouter, Depends, Form, HTTPException, Request
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
    error = request.query_params.get("error")
    success = request.query_params.get("success")
    return templates.TemplateResponse(
        request, "auth/login.html", {"error": error, "success": success}
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(None),
    username: str = Form(None),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func, or_
    from app.main import templates

    identifier = (username or email or "").strip().lower()
    if not identifier or not password:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Please provide both your username/email and password."},
            status_code=400,
        )

    result = await db.execute(
        select(UserProfile).where(
            or_(
                func.lower(UserProfile.email) == identifier,
                func.lower(UserProfile.username) == identifier,
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid username/email or password."},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "This account is deactivated. Please contact your System Administrator."},
            status_code=403,
        )

    if not user.check_password(password):
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Invalid username/email or password."},
            status_code=401,
        )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.get("/seed-db")
async def trigger_db_seed(request: Request):
    raise HTTPException(status_code=404, detail="Seed endpoint is permanently disabled.")


@router.get("/signup")
async def signup_page(request: Request):
    return RedirectResponse(
        url="/auth/login?error=Self-registration+is+disabled.+User+accounts+are+created+by+System+Administrator.",
        status_code=303,
    )


@router.post("/signup")
async def signup(request: Request):
    return RedirectResponse(
        url="/auth/login?error=Self-registration+is+disabled.+User+accounts+are+created+by+System+Administrator.",
        status_code=303,
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=303)
