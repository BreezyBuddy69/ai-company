from fastapi import HTTPException, Request

from app.config import get_settings


def _client_ip(request: Request, settings) -> str | None:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def require_api_key(request: Request) -> None:
    """Shared-secret + optional IP allowlist check for API routes exposed to
    the public internet.

    Not Traefik basicauth: the dashboard calls this API cross-origin via
    fetch(), and a browser can't complete an HTTP basic-auth challenge for a
    CORS request — the preflight OPTIONS gets a 401 with no CORS headers and
    the browser aborts with a plain "Failed to fetch". A header the frontend
    sets itself sidesteps that entirely.

    The IP check is a second, independent layer (ALLOWED_IPS in .env): even
    a leaked X-API-Key is useless from an unrecognized address. It's opt-in
    and best-effort — home IPs change and a misconfigured allowlist locks
    you out of your own API, so leave it unset unless you have a static IP
    to pin it to.
    """
    settings = get_settings()

    if settings.allowed_ip_list:
        client_ip = _client_ip(request, settings)
        if client_ip not in settings.allowed_ip_list:
            raise HTTPException(403, "IP not in ALLOWED_IPS allowlist")

    if not settings.api_key:
        return  # no key configured (e.g. local dev) — leave open
    if request.headers.get("x-api-key") != settings.api_key:
        raise HTTPException(401, "missing or invalid X-API-Key")
