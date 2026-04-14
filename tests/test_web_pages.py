"""Tests for web dashboard pages (Jinja2 templates)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from infrastructure.database.models.bot_instance import BotInstanceTable
from infrastructure.database.models.company import CompanyTable


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
    }
    data[field] = value
    resp = await auth_client.post("/bots", data=data)
    assert resp.status_code == 400
    assert "Invalid" in resp.text


# ── Toggle bot ──────────────────────────────────────────────────────

BOT_TOGGLE_PARAMS = [
    ("TG", "finance"),
    ("YM", "hr"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("messenger,module", BOT_TOGGLE_PARAMS)
async def test_toggle_bot_cycle(
    auth_client: AsyncClient,
    db_session,
    messenger: str,
    module: str,
):
    """Create → toggle active→inactive → toggle inactive→active."""
    token = f"toggle_{messenger}_{module}"

    # Create bot
    resp = await auth_client.post(
        "/bots",
        data={"token": token, "messenger_type": messenger, "module_type": module},
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
    assert resp.status_code == 200
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
    assert resp.status_code == 200

    # Logout with HTMX request
    resp = await client.post(
        "/auth/cookie/logout",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("HX-Redirect") == "/login"
