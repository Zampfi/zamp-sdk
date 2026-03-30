import asyncio
import json
from typing import Any, Dict, NoReturn, Optional, Union

import aiohttp
import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


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
