import asyncio
import contextvars
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from zamp_sdk.context import ExecutionHost, current_execution_host
from zamp_sdk.evals.constants import SYNC_CALL_ON_ACTIONS_HUB_ERROR

ResultT = TypeVar("ResultT")


def run_blocking(coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    # A sync caller may already be inside a running loop, where asyncio.run refuses to start; a new thread has none.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(contextvars.copy_context().run, asyncio.run, coroutine).result()


def raise_if_on_actions_hub(name: str, func: Callable[..., object]) -> None:
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        raise RuntimeError(SYNC_CALL_ON_ACTIONS_HUB_ERROR.format(name=name, function=func.__qualname__))
