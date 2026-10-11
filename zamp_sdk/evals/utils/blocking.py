import asyncio
import contextvars
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

ResultT = TypeVar("ResultT")


def run_blocking(coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(contextvars.copy_context().run, asyncio.run, coroutine).result()
