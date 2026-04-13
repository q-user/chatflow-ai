"""Web Dashboard pages (Jinja2 + HTMX)."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.auth import current_active_user_cookie
from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.user import UserTable
from infrastructure.database.session import get_db_session

# Resolve templates directory relative to this file
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Valid values for form fields
ALLOWED_MESSENGER_TYPES = {"TG", "YM"}
ALLOWED_MODULE_TYPES = {"finance", "estimator", "hr"}


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: UserTable = Depends(current_active_user_cookie),
    session: AsyncSession = Depends(get_db_session),
):
    """Render dashboard with user info and bot list.

    :param user: Current authenticated user (cookie-only auth).
    :param session: DB session for querying bots.
    """
    result = await session.execute(
        select(BotInstanceTable).where(BotInstanceTable.company_id == user.company_id)
    )
    bots = result.scalars().all()

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user, "bots": bots},
    )


@router.get("/bots/add", response_class=HTMLResponse)
async def bot_add_form(request: Request):
    """Return bot creation form partial (HTMX)."""
    return templates.TemplateResponse("partials/bot_form.html", {"request": request})


@router.post("/bots", response_class=HTMLResponse)
async def create_bot(
    request: Request,
    token: str = Form(...),
    messenger_type: str = Form(...),
    module_type: str = Form(...),
    user: UserTable = Depends(current_active_user_cookie),
    session: AsyncSession = Depends(get_db_session),
):
    """Create BotInstance and return updated bot table partial.

    :param token: Bot API token.
    :param messenger_type: "TG" or "YM".
    :param module_type: "finance", "estimator", "hr".
    """
    if messenger_type not in ALLOWED_MESSENGER_TYPES:
        raise HTTPException(400, f"Invalid messenger_type: {messenger_type}")
    if module_type not in ALLOWED_MODULE_TYPES:
        raise HTTPException(400, f"Invalid module_type: {module_type}")

    bot = BotInstanceTable(
        company_id=user.company_id,
        token=token,
        messenger_type=messenger_type,
        module_type=module_type,
        status="active",
    )
    session.add(bot)
    await session.commit()
    await session.refresh(bot)

    # Re-query all bots for the company
    result = await session.execute(
        select(BotInstanceTable).where(BotInstanceTable.company_id == user.company_id)
    )
    bots = result.scalars().all()

    return templates.TemplateResponse(
        "partials/bot_table.html",
        {"request": request, "bots": bots},
    )


@router.post("/bots/{bot_id}/toggle", response_class=HTMLResponse)
async def toggle_bot(
    request: Request,
    bot_id: uuid.UUID,
    user: UserTable = Depends(current_active_user_cookie),
    session: AsyncSession = Depends(get_db_session),
):
    """Toggle bot status active ↔ inactive. Return updated bot table."""
    result = await session.execute(
        select(BotInstanceTable).where(
            BotInstanceTable.id == bot_id,
            BotInstanceTable.company_id == user.company_id,
        )
    )
    bot = result.scalar_one_or_none()
    if bot is None:
        return HTMLResponse("Bot not found", status_code=404)

    bot.status = "inactive" if bot.status == "active" else "active"
    await session.commit()

    # Re-query all bots
    result = await session.execute(
        select(BotInstanceTable).where(BotInstanceTable.company_id == user.company_id)
    )
    bots = result.scalars().all()

    return templates.TemplateResponse(
        "partials/bot_table.html",
        {"request": request, "bots": bots},
    )
