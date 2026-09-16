import asyncio
import json
from typing import Any, Dict, NoReturn, Optional, Union

import aiohttp
from pydantic import BaseModel

from zamp_sdk.logger import get_logger

logger = get_logger(__name__)


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


class HttpClient:
    """Lightweight async HTTP client for JSON API calls."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        timeout: float = 30,
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

    @staticmethod
    def _server_message(response_text: str) -> Optional[str]:
        """The human-readable message inside an error body, if it carries one.

        The platform's rejections are a flat ``{"code": ..., "message": ...}``
        document; a wrapped ``{"error": {"message": ...}}`` envelope and FastAPI's
        string ``detail`` are read too. Surfacing it is what tells a caller *why* a
        4xx happened: the platform is the only gate on what an action may do, so its
        sentence is the whole explanation they get.
        """
        try:
            parsed = json.loads(response_text)
        except (TypeError, ValueError):
            return None
        if not isinstance(parsed, dict):
            return None
        err = parsed.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err:
            return err
        for key in ("message", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: Optional[Union[Dict[str, Any], BaseModel]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        raise_on_envelope_error: bool = True,
    ) -> dict:
        """Issue the request and return the parsed JSON body.

        ``raise_on_envelope_error`` treats a 2xx body with a non-null top-level
        ``error`` as a failed call. That is right for the platform's response
        envelope but wrong for an action document, whose ``error`` field is the
        action's own failure message and is read by the caller: pass ``False`` there
        so the document comes back whole.
        """
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

                    if not response.ok:
                        message = f"HTTP {response.status} from {url}"
                        server_message = self._server_message(response_text)
                        if server_message:
                            message = f"{message}: {server_message}"
                        raise HttpClientError(
                            message,
                            status_code=response.status,
                            response_body=response_text,
                        )

                    parsed: dict = json.loads(response_text)
                    if raise_on_envelope_error and isinstance(parsed, dict) and parsed.get("error") is not None:
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
        timeout: Optional[float] = None,
        raise_on_envelope_error: bool = True,
    ) -> dict:
        return await self._request(
            "POST",
            endpoint,
            data=data,
            headers=headers,
            timeout=timeout,
            raise_on_envelope_error=raise_on_envelope_error,
        )

    async def get(
        self,
        endpoint: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        return await self._request("GET", endpoint, headers=headers, timeout=timeout)
