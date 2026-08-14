from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserProfile
from app.categories.models import Category
from app.database import get_db
from app.dependencies import get_current_user

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_categories(
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.main import templates

    result = await db.execute(select(Category).order_by(Category.name))
    categories = result.scalars().all()
    return templates.TemplateResponse(
        request, "categories/list.html", {"user": user, "categories": categories}
    )


@router.post("")
async def create_category(
    name: str = Form(...),
    description: str = Form(""),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    category = Category(name=name, description=description or None)
    db.add(category)
    return RedirectResponse(url="/categories?success=1", status_code=303)


@router.post("/{category_id}")
async def update_category(
    category_id: str,
    name: str = Form(...),
    description: str = Form(""),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Category).where(Category.id == category_id))
    cat = result.scalar_one_or_none()
    if cat:
        cat.name = name
        cat.description = description or None
    return RedirectResponse(url="/categories?success=1", status_code=303)


@router.post("/{category_id}/delete")
async def delete_category(
    category_id: str,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Category).where(Category.id == category_id))
    cat = result.scalar_one_or_none()
    if cat:
        await db.delete(cat)
    return RedirectResponse(url="/categories?success=1", status_code=303)
