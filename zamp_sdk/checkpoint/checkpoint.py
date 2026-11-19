import asyncio
import hashlib
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from zamp_sdk.context import ENV_RERUN_CHAIN_ID, ENV_TOOL_CALL_ID
from zamp_sdk.logger import get_logger

logger = get_logger(__name__)


class Checkpoint:
    """Make a script resumable: a step that already ran is skipped when the script is re-run from the top.

    Progress is a JSON file in the current working directory, rewritten atomically after every step. It is
    keyed by ``ZAMP_RERUN_CHAIN_ID`` (the platform sets it on every re-run of one script), else
    ``ZAMP_TOOL_CALL_ID``, so a fresh run never skips work because of an older, abandoned one. Pass ``key=``
    to run outside the platform. With neither env var nor ``key``, progress is kept in memory only: steps
    still run and cache within that instance, but no file is written and nothing is resumed across runs (a warning
    is logged).

    Step results must be JSON-serialisable. A result is returned as its JSON round trip (a tuple becomes a
    list) on the first run too, so the first run and a re-run see the same value.

    Concurrent ``once`` calls for the same step on one instance run ``fn`` once: later callers wait for the
    first and get its saved result.
    """

    def __init__(self, key: str | None = None) -> None:
        self._step_locks: dict[str, asyncio.Lock] = {}
        run_key = key or os.environ.get(ENV_RERUN_CHAIN_ID) or os.environ.get(ENV_TOOL_CALL_ID)
        if not run_key:
            self._path: Path | None = None
            self._memory: dict[str, Any] = {}
            logger.warning(
                f"Checkpoint has no run key ({ENV_RERUN_CHAIN_ID} / {ENV_TOOL_CALL_ID} unset, no key=); "
                "progress will not be resumed if the script is re-run"
            )
            return
        digest = hashlib.sha256(run_key.encode()).hexdigest()[:16]
        self._path = Path.cwd() / f".zamp_checkpoint_{digest}.json"

    def _load(self) -> dict[str, Any]:
        if self._path is None:
            return self._memory
        try:
            return json.loads(self._path.read_text())
        except FileNotFoundError:
            return {}

    def _record(self, step: str, result: Any) -> Any:
        try:
            text = json.dumps(result)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"Checkpoint step {step!r} returned a result that is not JSON-serialisable: {exc}") from exc
        saved = {**self._load(), step: json.loads(text)}
        if self._path is None:
            self._memory = saved
            return saved[step]
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".zamp_checkpoint_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(saved, handle)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return saved[step]

    async def once(self, step: str, fn: Callable[[], Any | Awaitable[Any]]) -> Any:
        """Run ``fn`` (sync or async) unless ``step`` is already recorded; return its saved result."""
        async with self._step_locks.setdefault(step, asyncio.Lock()):
            saved = self._load()
            if step in saved:
                return saved[step]
            result = fn()
            if inspect.isawaitable(result):
                result = await result
            return self._record(step, result)

    def value(self, step: str, fn: Callable[[], Any]) -> Any:
        """Freeze ``fn()`` (e.g. a timestamp) on first use so every re-run gets the same value."""
        saved = self._load()
        if step in saved:
            return saved[step]
        return self._record(step, fn())

    def clear(self) -> None:
        """Delete the saved progress."""
        if self._path is None:
            self._memory = {}
        else:
            self._path.unlink(missing_ok=True)
