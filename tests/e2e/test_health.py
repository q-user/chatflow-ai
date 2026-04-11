import pytest
from httpx import ASGITransport, AsyncClient
from presentation.api.main import app


@pytest.mark.asyncio
async def test_health_check_returns_200():
    """
    Простейший E2E тест для проверки работоспособности каркаса FastAPI.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
