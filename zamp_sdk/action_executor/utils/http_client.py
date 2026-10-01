import asyncio
import json
import math
from typing import Any, Dict, NoReturn, Optional, Union

import aiohttp
from pydantic import BaseModel

from zamp_sdk.action_executor.constants import (
    HTTP_TOO_MANY_REQUESTS,
    RATE_LIMITED_PREFIX,
    RETRY_AFTER_HEADER,
    USER_AGENT,
    USER_AGENT_HEADER,
)
from zamp_sdk.logger import get_logger

logger = get_logger(__name__)

# The message of a 429 that carries no explanation of its own: one from a proxy or load
# balancer in front of the platform rather than from the platform.
_DEFAULT_RATE_LIMITED_MESSAGE = "Too many requests."


class HttpClientError(Exception):
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(self.message)


class RateLimitedError(HttpClientError):
    """The platform refused the request for a rate limit. Nothing was started.

    ``message`` is the platform's own explanation, written to be read as it is: who is over
    which limit, how long to wait, and not to retry in a loop. ``retry_after`` is the seconds
    until a retry can succeed; ``None`` when the platform said a retry can never fit the limit,
    or said nothing. ``check`` is ``"org"`` or ``"principal"`` (the user or agent), and
    ``limit_class`` the kind of work refused (``"sdk.action"``, ``"sdk.run"``, ...); each is
    ``None`` when the refusal did not state it.

    A subclass of :class:`HttpClientError` with ``status_code`` 429, so a handler written before
    this type existed still catches it, and its text still starts ``HTTP 429 from <url>``.
    ``status_code`` is ``None`` for a refusal that arrived in-band, inside a successful response
    (see ``rate_limit_refusal``); its text is then the ``RATE_LIMITED: ...`` string.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        check: Optional[str] = None,
        limit_class: Optional[str] = None,
        status_code: Optional[int] = HTTP_TOO_MANY_REQUESTS,
        response_body: Optional[str] = None,
        url: Optional[str] = None,
    ):
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.retry_after = retry_after
        self.check = check
        self.limit_class = limit_class
        self.url = url

    def __str__(self) -> str:
        if self.status_code is None:
            return f"{RATE_LIMITED_PREFIX} {self.message}"
        source = f"HTTP {self.status_code} from {self.url}" if self.url else f"HTTP {self.status_code}"
        return f"{source}: {self.message}"

    def __repr__(self) -> str:
        """The same text as ``str()``, so a refusal printed with ``!r`` still reads ``HTTP 429 ...``
        (or ``RATE_LIMITED: ...``), as an ``HttpClientError`` for a 429 always did."""
        return f"{type(self).__name__}({str(self)!r})"

    @classmethod
    def from_response(cls, *, url: str, body: str, retry_after_header: Optional[str]) -> "RateLimitedError":
        """Read a 429: the platform's JSON body and its ``Retry-After`` header.

        Both give the wait, as the same number; the header wins, being the standard. Tolerant: a
        429 from something in front of the platform has no such body and still becomes this
        error, with whatever it did say.
        """
        payload = _json_object(body)
        details = payload.get("details")
        if not isinstance(details, dict):
            details = {}
        message = payload.get("message")
        retry_after = _seconds(retry_after_header)
        if retry_after is None:
            retry_after = _seconds(details.get("retry_after_seconds"))
        return cls(
            message if isinstance(message, str) and message.strip() else _DEFAULT_RATE_LIMITED_MESSAGE,
            retry_after=retry_after,
            check=_optional_str(details.get("check")),
            limit_class=_optional_str(details.get("limit_class")),
            response_body=body,
            url=url,
        )


def _json_object(text: str) -> Dict[str, Any]:
    """``text`` parsed as a JSON object, or an empty dict when it is not one."""
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _seconds(value: Any) -> Optional[float]:
    """A wait in seconds, from a header or a JSON value; ``None`` when it is not one.

    Only ``Retry-After``'s delta-seconds form, which is what the platform sends. Anything that
    is not a finite, non-negative number reads as no wait given.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


class HttpClient:
    """Lightweight async HTTP client for JSON API calls."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ):
        self.base_url = base_url
        self.default_headers = default_headers or {}
        self.timeout = timeout

    def _build_url(self, endpoint: str) -> str:
        if self.base_url:
            return f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        return endpoint

    def _handle_request_error(self, exc: Exception) -> NoReturn:
        if isinstance(exc, HttpClientError):
            raise exc
        elif isinstance(exc, asyncio.TimeoutError):
            raise HttpClientError(f"Request timed out: {exc}")
        elif isinstance(exc, aiohttp.ClientError):
            raise HttpClientError(f"Network error: {exc}")
        else:
            raise HttpClientError(f"Unexpected error: {exc}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: Optional[Union[Dict[str, Any], BaseModel]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        try:
            request_headers = {USER_AGENT_HEADER: USER_AGENT, **self.default_headers}
            if headers:
                request_headers.update(headers)

            url = self._build_url(endpoint)

            request_data = None
            if data is not None:
                if isinstance(data, BaseModel):
                    request_data = data.model_dump_json()
                else:
                    request_data = json.dumps(data)
                request_headers.setdefault("Content-Type", "application/json")

            client_timeout = aiohttp.ClientTimeout(total=timeout or self.timeout)

            logger.info("API request", method=method, url=url)

            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    data=request_data,
                ) as response:
                    response_text = await response.text()

                    if response.status == HTTP_TOO_MANY_REQUESTS:
                        raise RateLimitedError.from_response(
                            url=url,
                            body=response_text,
                            retry_after_header=response.headers.get(RETRY_AFTER_HEADER),
                        )
                    if not response.ok:
                        raise HttpClientError(
                            f"HTTP {response.status} from {url}",
                            status_code=response.status,
                            response_body=response_text,
                        )

                    parsed: dict = json.loads(response_text)
                    if isinstance(parsed, dict) and parsed.get("error") is not None:
                        err = parsed["error"]
                        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                        raise HttpClientError(
                            msg,
                            status_code=response.status,
                            response_body=response_text,
                        )
                    if isinstance(parsed, dict) and "data" in parsed and parsed.get("error") is None:
                        return {"payload": parsed["data"]}
                    return parsed

        except Exception as e:
            self._handle_request_error(e)

    async def post(
        self,
        endpoint: str,
        *,
        data: Optional[Union[Dict[str, Any], BaseModel]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        return await self._request("POST", endpoint, data=data, headers=headers, timeout=timeout)

    async def get(
        self,
        endpoint: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        return await self._request("GET", endpoint, headers=headers, timeout=timeout)
