"""Base class for HTTP-based messenger adapters."""

import asyncio

import httpx
from infrastructure.config import settings


class BaseHttpAdapter:
    """Provides shared HTTP client management for messenger adapters."""

    _use_proxy: bool = False

    def __init__(
        self, http_client: httpx.AsyncClient | None = None, timeout: float = 30.0
    ):
        self._http: httpx.AsyncClient | None = http_client
        self._owns_client = http_client is None
        self._timeout = timeout
        self._client_lock = asyncio.Lock()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy httpx client creation with proxy support (thread-safe)."""
        if self._http is not None:
            return self._http
        async with self._client_lock:
            if self._http is not None:
                return self._http
            kwargs: dict = {"timeout": self._timeout}
            if self._use_proxy and settings.telegram_proxy:
                kwargs["proxy"] = settings.telegram_proxy
            self._http = httpx.AsyncClient(**kwargs)
        return self._http  # type: ignore[return-value]

    async def aclose(self) -> None:
        """Close the underlying httpx client if we created it."""
        async with self._client_lock:
            if self._owns_client and self._http is not None:
                await self._http.aclose()
                self._http = None
