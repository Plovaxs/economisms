"""The security and cache headers the gateway stamps onto EVERY response it
emits -- its own pages and errors, the static frontend, and relayed
upstream responses alike.

The gateway is the only component a browser talks to, so it is the one
place these are enforced. Headers that carry a security decision
(`x-content-type-options`, `x-frame-options`, ...) are always REPLACED,
never merged: an upstream that sends a weaker value, or none, cannot
change what the browser is told. A `content-security-policy` an upstream
chose deliberately is kept; otherwise the strictest policy that still
works for the response's content type is applied.
"""

from __future__ import annotations

HeaderList = list[tuple[bytes, bytes]]

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
API_CSP = "default-src 'none'; frame-ancestors 'none'"

_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)
_HSTS = "max-age=63072000; includeSubDomains"

_ENFORCED: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", _PERMISSIONS_POLICY.encode("ascii")),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"x-permitted-cross-domain-policies", b"none"),
)
_DROPPED = frozenset({b"server", b"x-powered-by", b"strict-transport-security"})

IMMUTABLE_CACHE = b"public, max-age=31536000, immutable"
REVALIDATE_CACHE = b"no-cache"
NO_STORE_CACHE = b"no-store"


def finalize_headers(headers: HeaderList, *, https: bool, is_html: bool) -> HeaderList:
    """Return `headers` with the enforced security headers applied.

    `is_html` selects the SPA policy over the API one for responses that
    carry no `content-security-policy` of their own. HSTS is only ever
    sent over HTTPS -- browsers ignore it on cleartext, and sending it
    there would be a false statement about the transport."""
    enforced = {name for name, _ in _ENFORCED}
    kept = [
        (name, value)
        for name, value in headers
        if name.lower() not in enforced and name.lower() not in _DROPPED
    ]
    if not any(name.lower() == b"content-security-policy" for name, _ in kept):
        policy = SPA_CSP if is_html else API_CSP
        if https and is_html:
            policy += "; upgrade-insecure-requests"
        kept.append((b"content-security-policy", policy.encode("ascii")))
    kept.extend(_ENFORCED)
    if https:
        kept.append((b"strict-transport-security", _HSTS.encode("ascii")))
    return kept


def set_default_header(headers: HeaderList, name: bytes, value: bytes) -> None:
    if not any(existing.lower() == name for existing, _ in headers):
        headers.append((name, value))
