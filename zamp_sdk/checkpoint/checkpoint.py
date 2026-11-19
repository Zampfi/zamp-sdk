import hashlib
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from zamp_sdk.context import ENV_RERUN_CHAIN_ID, ENV_TOOL_CALL_ID


class Checkpoint:
    """Make a script resumable: a step that already ran is skipped when the script is re-run from the top.

    Progress is a JSON file in the current working directory, rewritten atomically after every step. It is
    keyed by ``ZAMP_RERUN_CHAIN_ID`` (the platform sets it on every re-run of one script), else
    ``ZAMP_TOOL_CALL_ID``, so a fresh run never skips work because of an older, abandoned one. Pass ``key=``
    to run outside the platform; with neither env var nor ``key``, construction raises ``ValueError``.

    Step results must be JSON-serialisable. A result is returned as its JSON round trip (a tuple becomes a
    list) on the first run too, so the first run and a re-run see the same value.
    """

    def __init__(self, key: str | None = None) -> None:
        run_key = key or os.environ.get(ENV_RERUN_CHAIN_ID) or os.environ.get(ENV_TOOL_CALL_ID)
        if not run_key:
            raise ValueError(
                f"Checkpoint needs a run key: set {ENV_RERUN_CHAIN_ID} or {ENV_TOOL_CALL_ID}, or pass key="
            )
        digest = hashlib.sha256(run_key.encode()).hexdigest()[:16]
        self._path = Path.cwd() / f".zamp_checkpoint_{digest}.json"

    def _load(self) -> dict[str, Any]:
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
        self._path.unlink(missing_ok=True)
