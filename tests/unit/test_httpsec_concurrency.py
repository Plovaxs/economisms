from __future__ import annotations

import asyncio
import threading

import pytest

from prometheus.httpsec.concurrency import BoundedExecutor, Overloaded


def test_the_function_runs_in_a_worker_thread_and_its_result_comes_back() -> None:
    executor = BoundedExecutor(2)
    main = threading.get_ident()

    def work(a, b, *, scale):
        return (threading.get_ident(), (a + b) * scale)

    thread_id, value = asyncio.run(executor.run(work, 1, 2, scale=10))
    assert value == 30
    assert thread_id != main


def test_an_exception_in_the_worker_propagates_and_frees_the_slot() -> None:
    executor = BoundedExecutor(1)

    def fail():
        raise KeyError("nope")

    async def scenario():
        with pytest.raises(KeyError):
            await executor.run(fail)
        assert await executor.run(lambda: "after") == "after"

    asyncio.run(scenario())
    assert executor.inflight == 0


class Gate:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self):
        self.entered.set()
        assert self.release.wait(10)
        return "done"


def test_the_event_loop_keeps_running_while_a_worker_is_busy() -> None:
    executor = BoundedExecutor(1)
    gate = Gate()

    async def scenario():
        busy = asyncio.create_task(executor.run(gate))
        await asyncio.to_thread(gate.entered.wait, 5)
        ticks = 0
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1
        assert not busy.done()
        gate.release.set()
        return ticks, await busy

    ticks, result = asyncio.run(scenario())
    assert ticks == 5 and result == "done"


def test_work_beyond_the_bound_is_refused_immediately_not_queued() -> None:
    executor = BoundedExecutor(2)
    gates = [Gate(), Gate()]

    async def scenario():
        tasks = [asyncio.create_task(executor.run(g)) for g in gates]
        for g in gates:
            await asyncio.to_thread(g.entered.wait, 5)
        assert executor.inflight == 2
        with pytest.raises(Overloaded):
            await executor.run(lambda: "never")
        for g in gates:
            g.release.set()
        await asyncio.gather(*tasks)
        assert await executor.run(lambda: "again") == "again"

    asyncio.run(scenario())
    assert executor.inflight == 0


def test_cancelling_the_caller_does_not_free_the_slot_until_the_thread_finishes() -> None:
    executor = BoundedExecutor(1)
    gate = Gate()

    async def scenario():
        task = asyncio.create_task(executor.run(gate))
        await asyncio.to_thread(gate.entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert executor.inflight == 1, "the thread is still running"
        with pytest.raises(Overloaded):
            await executor.run(lambda: None)
        gate.release.set()
        for _ in range(100):
            if executor.inflight == 0:
                break
            await asyncio.sleep(0.02)
        return executor.inflight

    assert asyncio.run(scenario()) == 0


def test_an_unretrieved_exception_after_cancellation_does_not_warn(recwarn) -> None:
    executor = BoundedExecutor(1)
    release = threading.Event()
    entered = threading.Event()

    def fail_late():
        entered.set()
        release.wait(10)
        raise RuntimeError("late failure nobody is waiting for")

    async def scenario():
        task = asyncio.create_task(executor.run(fail_late))
        await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        for _ in range(100):
            if executor.inflight == 0:
                break
            await asyncio.sleep(0.02)

    asyncio.run(scenario())
    assert executor.inflight == 0


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "2", None])
def test_the_bound_must_be_a_positive_integer(bad) -> None:
    with pytest.raises(ValueError):
        BoundedExecutor(bad)  # type: ignore[arg-type]
