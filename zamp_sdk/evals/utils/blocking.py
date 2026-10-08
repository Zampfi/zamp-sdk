import asyncio
import contextvars
import threading
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


def run_blocking(coroutine: Coroutine[Any, Any, T]) -> T:
    """Runs a coroutine to completion from sync code, on its own thread so a running loop is never re-entered."""
    context = contextvars.copy_context()
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["value"] = context.run(asyncio.run, coroutine)
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
