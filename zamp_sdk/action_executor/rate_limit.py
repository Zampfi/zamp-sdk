"""Recognising a rate-limit refusal that did not arrive as an HTTP 429.

Some refusals are not HTTP errors. A spawned agent task that the platform refuses still
completes, with ``error="RATE_LIMITED: ..."`` in its result; inside the code executor a refused
call comes back as a FAILED envelope with the same kind of error. Both keep arriving as they
always have - raising for a completed action would change what a caller's success path
receives - so :func:`rate_limit_refusal` is the one place that recognises every shape.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from zamp_sdk.action_executor.constants import ACTION_ENVELOPE_KEYS, RATE_LIMITED_PREFIX
from zamp_sdk.action_executor.utils import RateLimitedError

# ActionExecutor raises a terminal failure as "Action <id> <status>: <error>".
_ACTION_FAILURE_PREFIX_RE = re.compile(r"^Action\s+\S+\s+\S+?:\s*")
# The wait an in-band refusal names ("Wait 24 s before retrying", or "retry after 24 s"). Read
# tolerantly: wording that does not match leaves retry_after as None rather than failing.
_IN_BAND_WAIT_RE = re.compile(r"\b(?:wait|retry after)\s+(\d+(?:\.\d+)?)\s*s\b", re.IGNORECASE)


def rate_limit_refusal(value: Any) -> RateLimitedError | None:
    """The rate-limit refusal ``value`` carries, as a :class:`RateLimitedError`, or ``None``.

    ``value`` is whatever an action call returned or raised:

    * a raised error: a :class:`RateLimitedError` itself (returned as it is), an error raised
      from one (an ``AgentDbError`` over a 429), or a failure whose error is an in-band refusal;
    * a returned result whose ``error`` is an in-band refusal, as a refused agent task's is;
    * an envelope from the code executor, refused (``FAILED``) or carrying a refused result;
    * the error string itself.

    An in-band refusal is an error that starts with ``RATE_LIMITED:``. Its ``retry_after`` is
    read from the text when the text names a wait; ``check`` and ``limit_class`` are ``None``.
    """
    if isinstance(value, BaseException):
        return _from_exception(value)
    if isinstance(value, Mapping):
        return _from_result(value)
    return _from_error_text(value)


def _from_exception(exc: BaseException) -> RateLimitedError | None:
    """The refusal ``exc`` is, or was raised from (``raise ... from``)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, RateLimitedError):
            return current
        refusal = _from_error_text(_ACTION_FAILURE_PREFIX_RE.sub("", str(current), count=1))
        if refusal is not None:
            return refusal
        current = current.__cause__
    return None


def _from_result(result: Mapping[str, Any]) -> RateLimitedError | None:
    """The refusal in a result's ``error``, or in the result an executor envelope wraps."""
    refusal = _from_error_text(result.get("error"))
    if refusal is None and ACTION_ENVELOPE_KEYS.issubset(result) and isinstance(result["result"], Mapping):
        refusal = _from_error_text(result["result"].get("error"))
    return refusal


def _from_error_text(text: Any) -> RateLimitedError | None:
    """A refusal from an error string that starts with the in-band prefix."""
    if not isinstance(text, str) or not text.strip().startswith(RATE_LIMITED_PREFIX):
        return None
    message = text.strip()[len(RATE_LIMITED_PREFIX) :].strip()
    wait = _IN_BAND_WAIT_RE.search(message)
    return RateLimitedError(
        message,
        retry_after=float(wait.group(1)) if wait else None,
        status_code=None,
    )
