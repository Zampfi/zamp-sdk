import asyncio
import json
import math
import re
from typing import Any, Dict, NoReturn, Optional, Union

import aiohttp
from pydantic import BaseModel

from zamp_sdk.action_executor.constants import HTTP_TOO_MANY_REQUESTS, RATE_LIMITED_PREFIX, RETRY_AFTER_HEADER
from zamp_sdk.logger import get_logger

logger = get_logger(__name__)

# The message of a 429 that carries none of its own: one from a proxy in front of the platform.
_DEFAULT_RATE_LIMITED_MESSAGE = "Too many requests."
# The wait an in-band refusal names: "... Wait 24 s before retrying; ...".
_IN_BAND_WAIT_RE = re.compile(r"\bWait (\d+(?:\.\d+)?) s\b")


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
    """The platform refused to start a call for a rate limit. Nothing was started.

    ``message`` is the platform's own explanation (who is over which limit, how long to wait, not
    to retry in a loop) and ``retry_after_seconds`` the wait it named, or ``None`` when no wait was
    named, as when the call can never fit the limit. ``status_code`` is always 429.

    The SDK raises it at once and never retries the call: for a ``POST`` answered 429, and for a
    refusal reported in-band. A subclass of :class:`HttpClientError`, so a handler written for that
    still catches it. A refusal over HTTP reads ``HTTP 429 from <url>: <message>``, starting as an
    HTTP 429 always has; a refusal that arrived in-band, as an action's ``RATE_LIMITED: ...`` error,
    reads as that error.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: Optional[float] = None,
        url: Optional[str] = None,
        response_body: Optional[str] = None,
    ):
        super().__init__(message, status_code=HTTP_TOO_MANY_REQUESTS, response_body=response_body)
        self.retry_after_seconds = retry_after_seconds
        self.url = url

    def __str__(self) -> str:
        if self.url is None:
            return f"{RATE_LIMITED_PREFIX} {self.message}"
        return f"HTTP {self.status_code} from {self.url}: {self.message}"

    @classmethod
    def from_response(cls, *, url: str, body: str, retry_after_header: Optional[str]) -> "RateLimitedError":
        """A 429: the message and the wait from the platform's JSON body, the wait from
        ``Retry-After`` when the body names none (a 429 from a proxy in front of the platform)."""
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            payload = {}
        details = payload.get("details")
        message = payload.get("message")
        retry_after = _seconds(details.get("retry_after_seconds")) if isinstance(details, dict) else None
        return cls(
            message if isinstance(message, str) and message.strip() else _DEFAULT_RATE_LIMITED_MESSAGE,
            retry_after_seconds=retry_after if retry_after is not None else _seconds(retry_after_header),
            url=url,
            response_body=body,
        )

    @classmethod
    def from_in_band(cls, error: str) -> "RateLimitedError":
        """An action's ``RATE_LIMITED: ...`` error, with the wait its text names."""
        message = error.removeprefix(RATE_LIMITED_PREFIX).strip()
        wait = _IN_BAND_WAIT_RE.search(message)
        return cls(message, retry_after_seconds=float(wait.group(1)) if wait else None)


def _seconds(value: Any) -> Optional[float]:
    """``value`` as a wait in seconds, or ``None`` when it is not a finite, non-negative number."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


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
            request_headers = {**self.default_headers}
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

                    # Only a POST asks to start something, so only its 429 is a refusal to start;
                    # a 429 on a read stays a plain HttpClientError.
                    if response.status == HTTP_TOO_MANY_REQUESTS and method == "POST":
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
