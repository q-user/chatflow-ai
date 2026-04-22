"""Base class for HTTP-based messenger adapters."""

import httpx
from infrastructure.config import settings


class BaseHttpAdapter:
    """Provides shared HTTP client management for messenger adapters."""

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._http: httpx.AsyncClient | None = http_client
        self._owns_client = http_client is None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy httpx client creation with proxy support."""
        if self._http is None:
            kwargs: dict = {"timeout": 30.0}
            if settings.telegram_proxy:
                kwargs["proxy"] = settings.telegram_proxy
            self._http = httpx.AsyncClient(**kwargs)
        return self._http

    async def aclose(self) -> None:
        """Close the underlying httpx client if we created it."""
        if self._owns_client and self._http is not None:
            await self._http.aclose()
            self._http = None
