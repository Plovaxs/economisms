"""The security and cache headers the gateway stamps onto EVERY response it
emits -- its own pages and errors, the static frontend, and relayed
upstream responses alike.

The mechanics (replace-never-merge, banner dropping, HSTS only over HTTPS)
are shared with the other ASGI apps in `prometheus.httpsec.headers`; what
lives here is the one policy that is specific to the gateway: the
Content-Security-Policy of the single-page app it serves.
"""

from __future__ import annotations

from prometheus.httpsec.headers import (
    API_CSP,
    IMMUTABLE_CACHE,
    NO_STORE_CACHE,
    REVALIDATE_CACHE,
    HeaderList,
    set_default_header,
)
from prometheus.httpsec.headers import finalize_headers as _finalize

__all__ = [
    "API_CSP",
    "IMMUTABLE_CACHE",
    "NO_STORE_CACHE",
    "REVALIDATE_CACHE",
    "SPA_CSP",
    "HeaderList",
    "finalize_headers",
    "set_default_header",
]

SPA_CSP = "; ".join(
    (
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "manifest-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
        "object-src 'none'",
    )
)


def finalize_headers(headers: HeaderList, *, https: bool, is_html: bool) -> HeaderList:
    """`is_html` selects the SPA policy over the API one for responses that
    carry no `content-security-policy` of their own."""
    return _finalize(
        headers,
        https=https,
        csp=SPA_CSP if is_html else API_CSP,
        upgrade_insecure_requests=is_html,
    )
