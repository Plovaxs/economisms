"""Security and cache headers every ASGI app in this project stamps onto
the responses it emits.

Headers that carry a security decision (`x-content-type-options`,
`x-frame-options`, ...) are always REPLACED, never merged: a response
that carries a weaker value, or none, cannot change what the browser is
told. A `content-security-policy` a response chose deliberately is kept;
otherwise the caller's policy is applied.
"""

from __future__ import annotations

HeaderList = list[tuple[bytes, bytes]]

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


def finalize_headers(
    headers: HeaderList,
    *,
    https: bool,
    csp: str = API_CSP,
    upgrade_insecure_requests: bool = False,
) -> HeaderList:
    """Return `headers` with the enforced security headers applied.

    HSTS (and `upgrade-insecure-requests`, when asked for) are only ever
    sent over HTTPS -- browsers ignore HSTS on cleartext, and sending it
    there would be a false statement about the transport."""
    enforced = {name for name, _ in _ENFORCED}
    kept = [
        (name, value)
        for name, value in headers
        if name.lower() not in enforced and name.lower() not in _DROPPED
    ]
    if not any(name.lower() == b"content-security-policy" for name, _ in kept):
        policy = csp
        if https and upgrade_insecure_requests:
            policy += "; upgrade-insecure-requests"
        kept.append((b"content-security-policy", policy.encode("ascii")))
    kept.extend(_ENFORCED)
    if https:
        kept.append((b"strict-transport-security", _HSTS.encode("ascii")))
    return kept


def set_default_header(headers: HeaderList, name: bytes, value: bytes) -> None:
    if not any(existing.lower() == name for existing, _ in headers):
        headers.append((name, value))
