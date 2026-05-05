"""Tests for web dashboard pages (Jinja2 templates)."""

import re
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.company import CompanyTable
from infrastructure.messengers import UnsupportedMessengerError


@pytest.mark.asyncio
async def test_login_page_renders(client: AsyncClient):
    """Test that /login returns 200 and renders login.html template."""
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "ChatFlow AI" in resp.text


# ── Dashboard auth ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_unauthenticated_api(client: AsyncClient):
    """API client (no Accept: text/html) → 401 JSON."""
    resp = await client.get("/dashboard")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_unauthenticated_browser(client: AsyncClient):
    """Browser client (Accept: text/html) → 303 redirect."""
    resp = await client.get("/dashboard", headers={"Accept": "text/html"})
    assert resp.status_code == 303


@pytest.mark.asyncio
async def test_dashboard_renders_for_authenticated_user(auth_client: AsyncClient):
    """Authenticated user gets dashboard with profile section."""
    resp = await auth_client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "ChatFlow AI" in resp.text
    assert "Профиль" in resp.text


# ── Bot form ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bot_add_form_requires_auth(client: AsyncClient):
    """GET /bots/add requires authentication."""
    resp = await client.get("/bots/add")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bot_add_form_returns_200(auth_client: AsyncClient):
    """Authenticated user gets bot form partial."""
    resp = await auth_client.get("/bots/add")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "token" in resp.text
    assert "messenger_type" in resp.text
    assert "module_type" in resp.text


# ── Create bot ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_bot_success(auth_client: AsyncClient):
    """POST /bots creates a bot and returns the bot table partial."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "test_token_123",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "TG" in resp.text
    assert "finance" in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("messenger_type", "INVALID"),
        ("module_type", "INVALID"),
    ],
)
async def test_create_bot_invalid_field(
    auth_client: AsyncClient, field: str, value: str
):
    """Invalid messenger_type or module_type returns 400."""
    data = {
        "token": "test_token",
        "messenger_type": "TG",
        "module_type": "finance",
        "ai_provider": "google",
        "ai_model": "gemini-3-flash-preview",
    }
    data[field] = value
    resp = await auth_client.post("/bots", data=data)
    assert resp.status_code == 400
    assert "Invalid" in resp.text


# ── Create bot: webhook failure ─────────────────────────────────────


@pytest.mark.asyncio
async def test_create_bot_webhook_failure_returns_400(
    auth_client: AsyncClient, mock_adapter: AsyncMock, db_session
):
    """register_webhook raises ValueError → 400, bot NOT created in DB."""
    mock_adapter.register_webhook.side_effect = ValueError("Invalid token")

    resp = await auth_client.post(
        "/bots",
        data={
            "token": "bad_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 400
    assert "Webhook registration failed" in resp.text

    # Verify bot was NOT created
    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "bad_token")
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_bot_unsupported_messenger_returns_400(
    auth_client: AsyncClient,
):
    """WA messenger type is not in ALLOWED_MESSENGER_TYPES → 400."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "some_token",
            "messenger_type": "WA",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 400
    assert "Invalid messenger_type" in resp.text


@pytest.mark.asyncio
async def test_create_adapter_unsupported_messenger_raises_501_equivalent():
    """create_adapter raises UnsupportedMessengerError for unknown types."""
    from infrastructure.messengers import create_adapter

    with pytest.raises(UnsupportedMessengerError):
        create_adapter("DISCORD", "some_token")


@pytest.mark.asyncio
async def test_create_bot_aclose_called_on_webhook_failure(
    auth_client: AsyncClient, mock_adapter: AsyncMock
):
    """aclose() is called even when register_webhook raises ValueError."""
    mock_adapter.register_webhook.side_effect = ValueError("Token rejected")

    await auth_client.post(
        "/bots",
        data={
            "token": "fail_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )

    mock_adapter.aclose.assert_awaited_once()


# ── Toggle bot ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_toggle_bot_cycle(
    auth_client: AsyncClient,
    db_session,
    messenger: str = "TG",
    module: str = "finance",
):
    """Create → toggle active→inactive → toggle inactive→active."""
    token = f"toggle_{messenger}_{module}"

    # Create bot
    resp = await auth_client.post(
        "/bots",
        data={
            "token": token,
            "messenger_type": messenger,
            "module_type": module,
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    # Fetch bot
    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == token)
    )
    bot = result.scalars().first()
    assert bot is not None
    assert bot.status == "active"

    # active → inactive
    resp = await auth_client.post(f"/bots/{bot.id}/toggle")
    assert resp.status_code == 200
    await db_session.refresh(bot)
    assert bot.status == "inactive"

    # inactive → active
    resp = await auth_client.post(f"/bots/{bot.id}/toggle")
    assert resp.status_code == 200
    await db_session.refresh(bot)
    assert bot.status == "active"


@pytest.mark.asyncio
async def test_toggle_bot_not_found(auth_client: AsyncClient):
    """Toggling a non-existent bot returns 404."""
    resp = await auth_client.post(f"/bots/{uuid.uuid4()}/toggle")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_toggle_bot_other_company_returns_404(
    auth_client: AsyncClient, db_session, test_company: CompanyTable
):
    """Toggling a bot from another company returns 404."""
    # Create bot in a different company
    other_bot = BotInstanceTable(
        company_id=test_company.id,
        messenger_type="TG",
        token="other_company_token",
    )
    db_session.add(other_bot)
    await db_session.flush()

    # Try to toggle it with auth_client (different company)
    resp = await auth_client.post(f"/bots/{other_bot.id}/toggle")
    assert resp.status_code == 404


# ── Auth required on mutating endpoints ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/bots"),
        ("post", "/bots/{id}/toggle"),
    ],
)
async def test_mutating_endpoints_require_auth(
    client: AsyncClient,
    method: str,
    path: str,
):
    """POST /bots and POST /bots/{id}/toggle require authentication."""
    url = path.format(id=uuid.uuid4())
    data = {
        "token": "test",
        "messenger_type": "TG",
        "module_type": "finance",
    }
    resp = await getattr(client, method)(url, data=data)
    assert resp.status_code in (307, 401)


# ── Dashboard with bots ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_shows_bot_table(auth_client: AsyncClient, db_session):
    """Dashboard renders bot table when bots exist for user's company."""
    # Create bot via API (ensures same company_id as auth user)
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "dashboard_test_token",
            "messenger_type": "TG",
            "module_type": "estimator",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    # Verify bot exists in DB
    result = await db_session.execute(select(BotInstanceTable))
    assert result.scalars().first() is not None

    resp = await auth_client.get("/dashboard")
    assert resp.status_code == 200
    assert "TG" in resp.text
    assert "estimator" in resp.text


# ── Entitlement enforcement ─────────────────────────────────────────


async def _create_user_in_company(
    client: AsyncClient, db_session, company, email_suffix: str = "example.com"
):
    """Register user via API (proper password hashing), then move to company."""
    test_email = f"entitlement_{uuid.uuid4().hex[:6]}@{email_suffix}"
    test_password = "SecureP@ss123"

    # Register via API (creates its own company, but that's fine)
    resp = await client.post(
        "/auth/register",
        json={
            "email": test_email,
            "password": test_password,
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )
    assert resp.status_code in (201, 400), f"Registration failed: {resp.text}"

    # Move user to target company
    from infrastructure.database.models.user import UserTable
    from sqlalchemy import select

    result = await db_session.execute(
        select(UserTable).where(UserTable.email == test_email)
    )
    user = result.scalar_one_or_none()
    assert user is not None
    user.company_id = company.id
    await db_session.flush()

    # Login
    resp = await client.post(
        "/auth/login",
        data={"username": test_email, "password": test_password},
    )
    assert resp.status_code == 200
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return user


@pytest.mark.asyncio
async def test_create_bot_restricted_company_returns_400(
    client: AsyncClient, db_session
):
    """Company with allowed_modules=['finance'] cannot create 'hr' bot → 400."""
    company = CompanyTable(
        name="Restricted Company",
        allowed_modules=["finance"],
    )
    db_session.add(company)
    await db_session.flush()

    await _create_user_in_company(client, db_session, company)

    # Try to create bot with module_type not in allowed_modules
    resp = await client.post(
        "/bots",
        data={
            "token": "restricted_bot_token",
            "messenger_type": "TG",
            "module_type": "hr",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 400
    assert "Invalid module_type" in resp.text


@pytest.mark.asyncio
async def test_create_bot_superuser_bypass(client: AsyncClient, db_session):
    """Superuser can create bot with any module_type, regardless of company entitlements."""
    company = CompanyTable(
        name="Superuser Company",
        allowed_modules=["finance"],
    )
    db_session.add(company)
    await db_session.flush()

    user = await _create_user_in_company(client, db_session, company)
    # Promote to superuser
    user.is_superuser = True
    await db_session.flush()

    # Superuser can create bot with module_type NOT in company.allowed_modules
    resp = await client.post(
        "/bots",
        data={
            "token": "super_bot_token",
            "messenger_type": "TG",
            "module_type": "hr",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200
    assert "hr" in resp.text


# ── Form renders only allowed modules ──────────────────────────────


@pytest.mark.asyncio
async def test_bot_form_renders_only_allowed_modules(client: AsyncClient, db_session):
    """GET /bots/add for company with ['finance'] → HTML has no <option value='hr'>."""
    company = CompanyTable(
        name="Finance-Only Company",
        allowed_modules=["finance"],
    )
    db_session.add(company)
    await db_session.flush()

    await _create_user_in_company(client, db_session, company)

    resp = await client.get("/bots/add")
    assert resp.status_code == 200
    # Should have finance option
    assert 'value="finance"' in resp.text
    # Should NOT have estimator or hr options
    assert 'value="estimator"' not in resp.text
    assert 'value="hr"' not in resp.text


# ── Empty allowed_modules ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_allowed_modules_form_empty(client: AsyncClient, db_session):
    """GET /bots/add for company with allowed_modules=[] → form has no module options."""
    company = CompanyTable(
        name="Empty Company",
        allowed_modules=[],
    )
    db_session.add(company)
    await db_session.flush()

    await _create_user_in_company(client, db_session, company)

    # Form should render but with no module options
    resp = await client.get("/bots/add")
    assert resp.status_code == 200
    assert 'value="finance"' not in resp.text
    assert 'value="estimator"' not in resp.text
    assert 'value="hr"' not in resp.text

    # Creating a bot should return 403
    resp = await client.post(
        "/bots",
        data={
            "token": "no_module_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 403
    assert "no allowed modules" in resp.text.lower()


# ── CompanyTable default allowed_modules ───────────────────────────


@pytest.mark.asyncio
async def test_company_default_allowed_modules(db_session):
    """New CompanyTable without explicit allowed_modules gets ['finance']."""
    company = CompanyTable(name="Default Company")
    db_session.add(company)
    await db_session.flush()

    # Check default value
    assert company.allowed_modules == ["finance"]


# ── OTP generation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_otp_generation_requires_auth(client: AsyncClient):
    """POST /dashboard/otp requires authentication."""
    resp = await client.post("/dashboard/otp")
    assert resp.status_code in (307, 401)


@pytest.mark.asyncio
async def test_otp_generation_success(auth_client: AsyncClient):
    """Authenticated user can generate OTP code and see it rendered."""
    resp = await auth_client.post("/dashboard/otp")
    assert resp.status_code == 200
    # Should show the 6-digit code
    assert "text-3xl" in resp.text
    assert "font-mono" in resp.text
    # Should not show error
    assert "red-50" not in resp.text


@pytest.mark.asyncio
async def test_otp_generation_rate_limit(auth_client: AsyncClient):
    """Second OTP request within 60s shows rate limit error message."""
    # First request — success
    resp = await auth_client.post("/dashboard/otp")
    assert resp.status_code == 200
    assert "text-3xl" in resp.text

    # Second request — rate limited
    resp = await auth_client.post("/dashboard/otp")
    assert resp.status_code == 200
    assert "Подождите 60 секунд" in resp.text


@pytest.mark.asyncio
async def test_otp_code_format(auth_client: AsyncClient):
    """OTP code in response is exactly 6 digits."""
    resp = await auth_client.post("/dashboard/otp")
    assert resp.status_code == 200
    # Extract code from HTML — rendered in <p class="... font-mono ...">
    match = re.search(r'<p[^>]*class="[^"]*font-mono[^"]*"[^>]*>(\d+)</p>', resp.text)
    assert match is not None, "OTP code element not found in response"
    code = match.group(1)
    assert code.isdigit(), f"OTP code '{code}' is not all digits"
    assert len(code) == 6, f"OTP code '{code}' is not 6 digits"


@pytest.mark.asyncio
async def test_dashboard_shows_otp_section(auth_client: AsyncClient):
    """Dashboard renders the OTP card with button and container."""
    resp = await auth_client.get("/dashboard")
    assert resp.status_code == 200
    assert "Привязка мессенджера" in resp.text
    assert "Сгенерировать код" in resp.text
    assert 'hx-post="/dashboard/otp"' in resp.text
    assert "otp-container" in resp.text


# ── HtmxAuthMiddleware HX-Redirect tests ────────────────────────────────


@pytest.mark.asyncio
async def test_htmx_middleware_login_redirect(client: AsyncClient):
    """HTMX login POST → HX-Redirect to /dashboard."""
    # First register
    test_email = f"htmx_login_{uuid.uuid4().hex[:6]}@example.com"
    await client.post(
        "/auth/register",
        json={
            "email": test_email,
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    # Login with HTMX request
    resp = await client.post(
        "/auth/cookie/login",
        data={"username": test_email, "password": "SecureP@ss123"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 204
    assert resp.headers.get("HX-Redirect") == "/dashboard"


@pytest.mark.asyncio
async def test_htmx_middleware_logout_redirect(client: AsyncClient):
    """HTMX logout POST → HX-Redirect to /login."""
    # First register and login to get cookie
    test_email = f"htmx_logout_{uuid.uuid4().hex[:6]}@example.com"
    await client.post(
        "/auth/register",
        json={
            "email": test_email,
            "password": "SecureP@ss123",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        },
    )

    # Cookie login to get session
    resp = await client.post(
        "/auth/cookie/login",
        data={"username": test_email, "password": "SecureP@ss123"},
    )
    assert resp.status_code == 204

    # Logout with HTMX request
    resp = await client.post(
        "/auth/cookie/logout",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 204
    assert resp.headers.get("HX-Redirect") == "/login"


# ── Bot edit ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_bot_get_form(auth_client: AsyncClient, db_session):
    """GET /bots/{id}/edit returns inline edit form with pre-filled values."""
    # Create a bot first
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_test_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    # Fetch bot ID
    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_test_token")
    )
    bot = result.scalar_one()

    # GET edit form
    resp = await auth_client.get(f"/bots/{bot.id}/edit")
    assert resp.status_code == 200
    assert 'value="edit_test_token"' in resp.text
    assert (
        'value="google" selected' in resp.text
        or "selected>Google AI Studio" in resp.text
    )


@pytest.mark.asyncio
async def test_edit_bot_post_success(auth_client: AsyncClient, db_session):
    """POST /bots/{id}/edit updates fields and returns updated row."""
    # Create bot
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_post_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_post_token")
    )
    bot = result.scalar_one()

    # Edit without changing token → no webhook re-register
    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_post_token",
            "messenger_type": "TG",
            "module_type": "estimator",
            "ai_provider": "nvidia",
            "ai_model": "moonshotai/kimi-k2.6",
        },
    )
    assert resp.status_code == 200
    assert "estimator" in resp.text
    assert "nvidia" not in resp.text  # row shows messenger_type, not provider

    # Verify DB update
    await db_session.refresh(bot)
    assert bot.module_type == "estimator"
    assert bot.config == {
        "llm_routing": {"provider": "nvidia", "model": "moonshotai/kimi-k2.6"}
    }


@pytest.mark.asyncio
async def test_edit_bot_post_invalid_provider(auth_client: AsyncClient, db_session):
    """POST /bots/{id}/edit with invalid ai_provider returns 400."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_inv_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_inv_token")
    )
    bot = result.scalar_one()

    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_inv_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "invalid_provider",
            "ai_model": "some-model",
        },
    )
    assert resp.status_code == 400
    assert "Invalid ai_provider" in resp.text


@pytest.mark.asyncio
async def test_edit_bot_post_webhook_reregister(auth_client: AsyncClient, db_session):
    """Changing token triggers webhook re-registration and succeeds."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_reg_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_reg_token")
    )
    bot = result.scalar_one()

    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_reg_token_changed",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    # Verify DB update
    await db_session.refresh(bot)
    assert bot.token == "edit_reg_token_changed"


@pytest.mark.asyncio
async def test_edit_bot_unauthorized_company(auth_client: AsyncClient, db_session):
    """GET /bots/{id}/edit for bot in another company returns 404."""
    from uuid import uuid4

    # Create a different company and bot under it
    other_company = CompanyTable(name="Other Company", allowed_modules=["finance"])
    db_session.add(other_company)
    await db_session.flush()

    other_bot = BotInstanceTable(
        id=uuid4(),
        company_id=other_company.id,
        token="other_token",
        messenger_type="TG",
        module_type="finance",
        status="active",
        config={
            "llm_routing": {"provider": "google", "model": "gemini-3-flash-preview"}
        },
    )
    db_session.add(other_bot)
    await db_session.commit()

    resp = await auth_client.get(f"/bots/{other_bot.id}/edit")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bot_row_endpoint(auth_client: AsyncClient, db_session):
    """GET /bots/{id}/row returns single bot row partial."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "row_test_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "row_test_token")
    )
    bot = result.scalar_one()

    resp = await auth_client.get(f"/bots/{bot.id}/row")
    assert resp.status_code == 200
    assert "row_test_token" not in resp.text  # row doesn't show token
    assert "TG" in resp.text
    assert "finance" in resp.text


@pytest.mark.asyncio
async def test_create_bot_invalid_ai_provider(auth_client: AsyncClient):
    """POST /bots with invalid ai_provider returns 400."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "test_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "invalid_provider",
            "ai_model": "some-model",
        },
    )
    assert resp.status_code == 400
    assert "Invalid ai_provider" in resp.text


@pytest.mark.asyncio
async def test_create_bot_invalid_ai_model(auth_client: AsyncClient):
    """POST /bots with ai_model not in provider returns 400."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "test_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "invalid-model",
        },
    )
    assert resp.status_code == 400
    assert "Invalid ai_model" in resp.text


@pytest.mark.asyncio
async def test_create_bot_mx_auto_secret(auth_client: AsyncClient, db_session):
    """POST /bots with messenger_type=MX and no secret auto-generates secret."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "mx_test_token",
            "messenger_type": "MX",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
            # secret omitted
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "mx_test_token")
    )
    bot = result.scalar_one()
    assert bot.secret is not None
    assert len(bot.secret) == 32  # uuid4().hex


@pytest.mark.asyncio
async def test_edit_bot_invalid_messenger_type(auth_client: AsyncClient, db_session):
    """POST /bots/{id}/edit with invalid messenger_type returns 400."""
    # Create bot via HTTP to get correct company_id
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_messenger_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_messenger_token")
    )
    bot = result.scalar_one()

    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_messenger_token",
            "messenger_type": "INVALID",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 400
    assert "Invalid messenger_type" in resp.text


@pytest.mark.asyncio
async def test_edit_bot_invalid_module_type(auth_client: AsyncClient, db_session):
    """POST /bots/{id}/edit with module_type not in allowed_modules returns 400."""
    # Create bot via HTTP to get correct company_id
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_module_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_module_token")
    )
    bot = result.scalar_one()

    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_module_token",
            "messenger_type": "TG",
            "module_type": "invalid_module",  # definitely not in allowed_modules
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 400
    assert "Invalid module_type" in resp.text


@pytest.mark.asyncio
async def test_edit_bot_invalid_ai_model(auth_client: AsyncClient, db_session):
    """POST /bots/{id}/edit with ai_model not in provider returns 400."""
    # Create bot via HTTP to get correct company_id
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_model_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_model_token")
    )
    bot = result.scalar_one()

    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_model_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "invalid-model",
        },
    )
    assert resp.status_code == 400
    assert "Invalid ai_model" in resp.text


@pytest.mark.asyncio
async def test_edit_bot_post_not_found(auth_client: AsyncClient):
    """POST /bots/{id}/edit for non-existent bot returns 404."""
    from uuid import uuid4

    fake_id = uuid4()
    resp = await auth_client.post(
        f"/bots/{fake_id}/edit",
        data={
            "token": "test_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_edit_bot_config_merge_preserves_system_prompt(
    auth_client: AsyncClient, db_session
):
    """POST /bots/{id}/edit preserves other config keys like system_prompt."""
    # Create bot via HTTP to get correct company_id
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_merge_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    # Inject system_prompt into config directly
    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_merge_token")
    )
    bot = result.scalar_one()
    bot.config = {
        "system_prompt": "Custom prompt",
        "llm_routing": {"provider": "google", "model": "gemini-3-flash-preview"},
    }
    await db_session.commit()

    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_merge_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "nvidia",
            "ai_model": "moonshotai/kimi-k2.6",
        },
    )
    assert resp.status_code == 200

    await db_session.refresh(bot)
    assert bot.config is not None
    assert bot.config.get("system_prompt") == "Custom prompt"
    assert bot.config.get("llm_routing") == {
        "provider": "nvidia",
        "model": "moonshotai/kimi-k2.6",
    }


@pytest.mark.asyncio
async def test_edit_bot_row_not_found(auth_client: AsyncClient):
    """GET /bots/{id}/row for non-existent bot returns 404."""
    from uuid import uuid4

    fake_id = uuid4()
    resp = await auth_client.get(f"/bots/{fake_id}/row")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_edit_bot_empty_secret_normalized(auth_client: AsyncClient, db_session):
    """POST /bots/{id}/edit with whitespace-only secret normalizes to None."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_secret_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_secret_token")
    )
    bot = result.scalar_one()

    # Send whitespace-only secret → should be treated as None (no re-register needed)
    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_secret_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
            "secret": "   ",
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_edit_bot_mx_auto_secret(auth_client: AsyncClient, db_session):
    """POST /bots/{id}/edit switching to MX auto-generates secret if empty."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_mx_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_mx_token")
    )
    bot = result.scalar_one()
    assert bot.secret is None  # TG bot has no secret

    # Switch to MX without secret
    resp = await auth_client.post(
        f"/bots/{bot.id}/edit",
        data={
            "token": "edit_mx_token",
            "messenger_type": "MX",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    await db_session.refresh(bot)
    assert bot.secret is not None
    assert len(bot.secret) == 32


@pytest.mark.asyncio
async def test_edit_bot_webhook_value_error(
    auth_client: AsyncClient, db_session, monkeypatch
):
    """POST /bots/{id}/edit with token change but webhook raises ValueError → 400."""
    resp = await auth_client.post(
        "/bots",
        data={
            "token": "edit_webhook_token",
            "messenger_type": "TG",
            "module_type": "finance",
            "ai_provider": "google",
            "ai_model": "gemini-3-flash-preview",
        },
    )
    assert resp.status_code == 200

    result = await db_session.execute(
        select(BotInstanceTable).where(BotInstanceTable.token == "edit_webhook_token")
    )
    bot = result.scalar_one()

    # Force adapter.register_webhook to raise ValueError
    from infrastructure.services.hook_router import get_adapter_factory
    from unittest.mock import AsyncMock

    failing_adapter = AsyncMock()
    failing_adapter.register_webhook = AsyncMock(side_effect=ValueError("bad webhook"))
    failing_adapter.aclose = AsyncMock()

    def failing_factory(messenger_type: str, token: str):
        return failing_adapter

    # Patch the factory in app dependency overrides
    app = auth_client._transport.app
    app.dependency_overrides[get_adapter_factory] = lambda: failing_factory

    try:
        resp = await auth_client.post(
            f"/bots/{bot.id}/edit",
            data={
                "token": "edit_webhook_token_changed",
                "messenger_type": "TG",
                "module_type": "finance",
                "ai_provider": "google",
                "ai_model": "gemini-3-flash-preview",
            },
        )
        assert resp.status_code == 400
        assert "Webhook registration failed" in resp.text
    finally:
        app.dependency_overrides.pop(get_adapter_factory, None)
