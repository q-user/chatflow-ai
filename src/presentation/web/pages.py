"""Web Dashboard pages (Jinja2 + HTMX)."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.auth import current_active_user_cookie
from infrastructure.config import ALL_MODULE_TYPES, settings
from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.company import CompanyTable
from infrastructure.database.models.user import UserTable
from infrastructure.database.session import get_db_session
from infrastructure.messengers import UnsupportedMessengerError, create_adapter
from core.interfaces.messenger import IMessengerAdapter
from presentation.api.otp import get_otp_service
from core.services.otp import OTPService, RateLimitExceeded

# Resolve templates directory relative to this file
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Disable template caching (cache_size=0) to avoid Python 3.14 LRU cache bug
# where dict objects cannot be used as cache keys
env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    cache_size=0,
    autoescape=select_autoescape(),
)

router = APIRouter()
templates = Jinja2Templates(env=env)

# Valid values for form fields
ALLOWED_MESSENGER_TYPES = {"TG", "MX"}


def _default_create_adapter(messenger_type: str, token: str) -> IMessengerAdapter:
    """Default adapter factory — uses the registry.

    Override via app.dependency_overrides[get_adapter] for testing.
    """
    return create_adapter(messenger_type, token)


async def get_adapter(
    messenger_type: str,
    token: str,
) -> IMessengerAdapter:
    """FastAPI dependency: creates a messenger adapter by type and token."""
    return _default_create_adapter(messenger_type, token)


def get_available_modules_for(
    user: UserTable, company: CompanyTable | None
) -> list[str]:
    """Compute allowed modules — superusers get all, otherwise company entitlements.

    Raises HTTPException(500) if company is None (data corruption).
    Returns empty list if company.allowed_modules is explicitly [].
    """
    if user.is_superuser:
        return list(ALL_MODULE_TYPES)

    # company=None should never happen — user.company_id is NOT NULL FK
    if company is None:
        raise HTTPException(500, "Company not found for user — data corruption")

    return company.allowed_modules


async def get_user_available_modules(
    user: UserTable = Depends(current_active_user_cookie),
    session: AsyncSession = Depends(get_db_session),
) -> list[str]:
    """FastAPI dependency: load company and compute allowed modules."""
    result = await session.execute(
        select(CompanyTable).where(CompanyTable.id == user.company_id)
    )
    company = result.scalar_one_or_none()
    return get_available_modules_for(user, company)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page."""
    return templates.TemplateResponse(request, "login.html")


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
        request,
        "dashboard.html",
        {"user": user, "bots": bots},
    )


@router.post("/dashboard/otp", response_class=HTMLResponse)
async def generate_otp_web(
    request: Request,
    user: UserTable = Depends(current_active_user_cookie),
    otp_service: OTPService = Depends(get_otp_service),
):
    """Generate OTP code and return result partial via HTMX."""
    try:
        code = await otp_service.generate_code(user.id)
        return templates.TemplateResponse(
            request, "partials/otp_result.html", {"code": code}
        )
    except RateLimitExceeded:
        return templates.TemplateResponse(
            request,
            "partials/otp_result.html",
            {"error": "Подождите 60 секунд перед повторной генерацией"},
        )


@router.get("/bots/add", response_class=HTMLResponse)
async def bot_add_form(
    request: Request,
    available_modules: list[str] = Depends(get_user_available_modules),
):
    """Return bot creation form partial (HTMX)."""
    return templates.TemplateResponse(
        request,
        "partials/bot_form.html",
        {"available_modules": available_modules},
    )


@router.post("/bots", response_class=HTMLResponse)
async def create_bot(
    request: Request,
    token: str = Form(...),
    messenger_type: str = Form(...),
    module_type: str = Form(...),
    secret: str | None = Form(None),
    user: UserTable = Depends(current_active_user_cookie),
    available_modules: list[str] = Depends(get_user_available_modules),
    session: AsyncSession = Depends(get_db_session),
    adapter: IMessengerAdapter = Depends(get_adapter),
):
    """Create BotInstance with webhook registration before DB insert.

    Flow:
    1. Validate messenger_type + module_type (unchanged)
    2. Generate bot_id upfront
    3. Build webhook_url from settings.domain
    4. adapter → register_webhook → aclose (try/finally)
    5. On success: create BotInstanceTable(id=bot_id) → commit → return table

    :param token: Bot API token.
    :param messenger_type: "TG", "MX".
    :param module_type: "finance", "estimator", "hr".
    :param secret: Optional webhook secret (MAX only).
    :param adapter: Injectable messenger adapter (overridden in tests).
    """
    if messenger_type not in ALLOWED_MESSENGER_TYPES:
        raise HTTPException(400, f"Invalid messenger_type: {messenger_type}")

    if not available_modules:
        raise HTTPException(
            403, "Your company has no allowed modules — cannot create bots"
        )

    if module_type not in available_modules:
        raise HTTPException(400, f"Invalid module_type: {module_type}")

    # Auto-generate secret for MAX bots (required for webhook verification)
    if messenger_type == "MX" and not secret:
        secret = uuid.uuid4().hex

    bot_id = uuid.uuid4()
    webhook_url = f"https://{settings.domain}/api/v1/hooks/{messenger_type}/{bot_id}"

    try:
        await adapter.register_webhook(webhook_url, secret=secret)
    except UnsupportedMessengerError as exc:
        raise HTTPException(501, f"Messenger type not yet supported: {exc}")
    except NotImplementedError as exc:
        raise HTTPException(501, f"Feature not yet implemented: {exc}")
    except ValueError as exc:
        raise HTTPException(400, f"Webhook registration failed: {exc}")
    finally:
        await adapter.aclose()

    bot = BotInstanceTable(
        id=bot_id,
        company_id=user.company_id,
        token=token,
        messenger_type=messenger_type,
        module_type=module_type,
        status="active",
        secret=secret,
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
        request,
        "partials/bot_table.html",
        {"bots": bots},
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
        request,
        "partials/bot_table.html",
        {"bots": bots},
    )
