"""Middleware for HTMX + fastapi-users cookie auth integration."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class HtmxAuthMiddleware(BaseHTTPMiddleware):
    """Add HX-Redirect header to successful cookie auth responses.

    fastapi-users cookie login returns JSON 200 + Set-Cookie.
    HTMX needs HX-Redirect to navigate to /dashboard after login.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # After successful cookie login → redirect to dashboard
        if (
            request.url.path == "/auth/cookie/login"
            and request.method == "POST"
            and response.status_code == 204
            and "HX-Request" in request.headers
        ):
            response.headers["HX-Redirect"] = "/dashboard"

        # After successful cookie logout → redirect to login
        elif (
            request.url.path == "/auth/cookie/logout"
            and request.method == "POST"
            and response.status_code == 204
            and "HX-Request" in request.headers
        ):
            response.headers["HX-Redirect"] = "/login"

        return response
