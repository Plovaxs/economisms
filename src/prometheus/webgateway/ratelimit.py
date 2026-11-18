"""A bounded, per-client token-bucket rate limiter for the gateway's edge.

`service.application.ResearchService` already budgets requests per
authenticated owner -- but it ALSO keeps one process-wide bucket that is
charged BEFORE authentication, so an unauthenticated client flooding the
gateway could otherwise exhaust the shared budget and lock every real
user out. This limiter runs in front of all of that, keyed by the real
client address, so one abusive address is throttled to its own allowance
and cannot spend anyone else's.

Memory is bounded no matter what a client does: at most `max_keys`
buckets are tracked, idle ones (indistinguishable from a brand-new
client) are reclaimed first, and once the table is genuinely full of
active clients every further new address shares ONE overflow bucket
rather than being allocated its own -- degraded fairness, never unbounded
growth. Single-event-loop use only (the gateway calls it from the loop
thread); the clock is injectable so every behaviour is testable without
sleeping.
"""

from __future__ import annotations

import ipaddress
import math
import time
from collections.abc import Callable
from typing import NamedTuple


class Decision(NamedTuple):
    allowed: bool
    retry_after_seconds: float


class TokenBucketLimiter:
    def __init__(
        self,
        *,
        rate_per_second: float,
        burst: int,
        max_keys: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(rate_per_second, bool)
            or not isinstance(rate_per_second, (int, float))
            or not math.isfinite(rate_per_second)
            or rate_per_second <= 0
        ):
            raise ValueError("rate_per_second must be a finite positive number")
        if type(burst) is not int or burst < 1:
            raise ValueError("burst must be a positive integer")
        if type(max_keys) is not int or max_keys < 1:
            raise ValueError("max_keys must be a positive integer")
        self.rate = float(rate_per_second)
        self.burst = burst
        self.max_keys = max_keys
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._overflow: tuple[float, float] = (float(burst), clock())
        self._next_sweep = clock()

    def acquire(self, key: str) -> Decision:
        now = self._clock()
        bucket = self._buckets.get(key)
        overflow = False
        if bucket is None:
            if len(self._buckets) >= self.max_keys:
                self._sweep(now)
            if len(self._buckets) >= self.max_keys:
                overflow = True
                bucket = self._overflow
            else:
                bucket = (float(self.burst), now)
        tokens, last = bucket
        tokens = min(float(self.burst), tokens + max(0.0, now - last) * self.rate)
        if tokens >= 1.0:
            result = Decision(True, 0.0)
            tokens -= 1.0
        else:
            result = Decision(False, (1.0 - tokens) / self.rate)
        if overflow:
            self._overflow = (tokens, now)
        else:
            self._buckets[key] = (tokens, now)
        return result

    def _sweep(self, now: float) -> None:
        # At most once per second: an attacker hammering a full table must
        # not be able to make every request pay for a full scan.
        if now < self._next_sweep:
            return
        self._next_sweep = now + 1.0
        full = float(self.burst)
        for key in [
            k
            for k, (tokens, last) in self._buckets.items()
            if tokens + max(0.0, now - last) * self.rate >= full
        ]:
            del self._buckets[key]

    def __len__(self) -> int:
        return len(self._buckets)


def client_key(host: str | None) -> str:
    """Normalize a peer address to a rate-limit key.

    IPv6 clients are keyed by their /64 (a single subscriber commonly
    controls a whole /64, so keying on the full address would let one
    client mint unlimited keys); IPv4-mapped IPv6 collapses onto the IPv4
    address; anything that is not an IP (a unix-socket peer) is used
    verbatim."""
    if not host:
        return "unknown"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host[:64]
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False).network_address) + "/64"
    return str(address)
