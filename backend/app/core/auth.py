from fastapi import HTTPException, Request

from app.config import get_settings


def require_api_key(request: Request) -> None:
    """Shared-secret check for API routes exposed to the public internet.

    Not Traefik basicauth: the dashboard calls this API cross-origin via
    fetch(), and a browser can't complete an HTTP basic-auth challenge for a
    CORS request — the preflight OPTIONS gets a 401 with no CORS headers and
    the browser aborts with a plain "Failed to fetch". A header the frontend
    sets itself sidesteps that entirely.
    """
    settings = get_settings()
    if not settings.api_key:
        return  # no key configured (e.g. local dev) — leave open
    if request.headers.get("x-api-key") != settings.api_key:
        raise HTTPException(401, "missing or invalid X-API-Key")
