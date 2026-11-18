"""A bounded in-flight executor for blocking work inside an ASGI app.

Blocking calls (a socket round-trip, a model-training computation, a
credentials-file read) must never run on the event loop: one slow call
would freeze every other request, the health probe included. They run in
a worker thread instead -- but a thread cannot be cancelled, so a bound on
how many may be in flight at once is what keeps a burst of slow requests
from oversubscribing the machine.

A slot is released when the worker thread actually FINISHES, not when the
request that started it is cancelled: a client that disconnects mid-call
must not let the next request start more work than the bound allows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class Overloaded(Exception):
    """Every in-flight slot is taken; the caller should answer 503."""


class BoundedExecutor:
    def __init__(self, max_inflight: int) -> None:
        if type(max_inflight) is not int or max_inflight < 1:
            raise ValueError("max_inflight must be a positive integer")
        self.max_inflight = max_inflight
        self._inflight = 0

    @property
    def inflight(self) -> int:
        return self._inflight

    async def run(self, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        if self._inflight >= self.max_inflight:
            raise Overloaded()
        self._inflight += 1
        task: asyncio.Future[T] = asyncio.ensure_future(asyncio.to_thread(func, *args, **kwargs))
        task.add_done_callback(self._release)
        return await asyncio.shield(task)

    def _release(self, task: asyncio.Future[T]) -> None:
        self._inflight -= 1
        if not task.cancelled():
            task.exception()  # mark retrieved; the awaiting request already handled it
