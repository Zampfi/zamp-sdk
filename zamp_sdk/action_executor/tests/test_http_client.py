import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zamp_sdk.action_executor.utils import HttpClient, HttpClientError, RateLimitedError


class TestHttpClientUrlBuilding:
    def test_builds_url_with_base(self):
        client = HttpClient(base_url="https://api.zamp.test")
        assert client._build_url("/actions") == "https://api.zamp.test/actions"

    def test_builds_url_strips_trailing_slash(self):
        client = HttpClient(base_url="https://api.zamp.test/")
        assert client._build_url("/actions") == "https://api.zamp.test/actions"

    # If the input URL is already absolute, it should be returned as-is regardless of the base URL.
    def test_builds_url_without_base(self):
        client = HttpClient()
        assert client._build_url("https://full.url/path") == "https://full.url/path"


class TestHttpClientPost:
    async def test_post_with_json_body(self):
        client = HttpClient(base_url="https://api.zamp.test")
        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=json.dumps({"id": "123"}))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=mock_ctx)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client.post("/actions", data={"name": "test"})

        assert result == {"id": "123"}

    async def test_post_raises_on_http_error(self):
        client = HttpClient(base_url="https://api.zamp.test")
        mock_response = AsyncMock()
        mock_response.ok = False
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=mock_ctx)

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            pytest.raises(HttpClientError, match="HTTP 500"),
        ):
            await client.post("/actions", data={"name": "test"})


class TestHttpClientGet:
    async def test_get_without_body(self):
        client = HttpClient(base_url="https://api.zamp.test")
        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=json.dumps({"status": "COMPLETED"}))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=mock_ctx)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client.get("/actions/123")

        assert result == {"status": "COMPLETED"}
        call_kwargs = mock_session.request.call_args.kwargs
        assert call_kwargs["data"] is None


class TestHttpClientEnvelopeUnwrapping:
    async def test_unwraps_data_envelope(self):
        client = HttpClient(base_url="https://api.zamp.test")
        envelope = {"data": {"payload": "inner"}, "error": None}
        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=json.dumps(envelope))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=mock_ctx)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await client.get("/test")

        assert result == {"payload": {"payload": "inner"}}

    async def test_raises_on_error_envelope(self):
        client = HttpClient(base_url="https://api.zamp.test")
        envelope = {"data": None, "error": {"message": "Not found"}}
        mock_response = AsyncMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=json.dumps(envelope))

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=mock_ctx)

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            pytest.raises(HttpClientError, match="Not found"),
        ):
            await client.get("/test")


class TestHttpClientErrorHandling:
    async def test_timeout_raises_http_client_error(self):
        client = HttpClient(base_url="https://api.zamp.test", timeout=1)

        with (
            patch("aiohttp.ClientSession", side_effect=TimeoutError("timed out")),
            pytest.raises(HttpClientError, match="Request timed out"),
        ):
            await client.get("/test")


def _session_returning(response) -> AsyncMock:
    """A mocked ``aiohttp.ClientSession`` whose one request answers ``response``."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.request = MagicMock(return_value=ctx)
    return session


def _response(status: int, body: str, headers: dict | None = None) -> AsyncMock:
    response = AsyncMock()
    response.ok = status < 400
    response.status = status
    response.text = AsyncMock(return_value=body)
    response.headers = headers or {}
    return response


# The platform's 429, as its rate limiter renders it.
_REFUSAL_MESSAGE = (
    "Your organization is using SDK actions faster than its limit (120 per minute). This request was NOT "
    "started. Wait 2 s before retrying; do not retry in a loop or in parallel. If you need a higher limit, "
    "contact support."
)


def _refusal_body(retry_after_seconds: int | None = 2) -> str:
    return json.dumps(
        {
            "type": "rate_limited",
            "code": "RATE_LIMITED",
            "message": _REFUSAL_MESSAGE,
            "details": {
                "limit_class": "sdk.action",
                "check": "org",
                "limit": 120,
                "period_seconds": 60,
                "burst": 30,
                "retry_after_seconds": retry_after_seconds,
            },
        }
    )


class TestHttpClientRateLimited:
    async def _refusal(self, response, method: str = "post") -> RateLimitedError:
        client = HttpClient(base_url="https://api.zamp.test")
        with (
            patch("aiohttp.ClientSession", return_value=_session_returning(response)),
            pytest.raises(RateLimitedError) as exc_info,
        ):
            await getattr(client, method)("/actions")
        return exc_info.value

    async def test_a_429_carries_the_platform_message_and_wait(self):
        body = _refusal_body()

        error = await self._refusal(_response(429, body, {"Retry-After": "2"}))

        assert error.message == _REFUSAL_MESSAGE
        assert error.retry_after_seconds == 2.0
        assert error.status_code == 429
        assert error.url == "https://api.zamp.test/actions"
        assert error.response_body == body

    async def test_it_still_reads_and_catches_as_an_http_429(self):
        """Handlers and agent prompts written for earlier SDKs key on this type and text."""
        error = await self._refusal(_response(429, _refusal_body(), {"Retry-After": "2"}))

        assert isinstance(error, HttpClientError)
        assert str(error) == f"HTTP 429 from https://api.zamp.test/actions: {_REFUSAL_MESSAGE}"

    async def test_the_body_gives_the_wait_before_the_header(self):
        error = await self._refusal(_response(429, _refusal_body(retry_after_seconds=2), {"Retry-After": "5"}))

        assert error.retry_after_seconds == 2.0

    async def test_a_429_from_in_front_of_the_platform_is_typed_with_its_header_wait(self):
        """A proxy's 429 has no JSON body: still a RateLimitedError, with what it did say."""
        error = await self._refusal(_response(429, "<html>Too Many Requests</html>", {"Retry-After": "3"}))

        assert error.retry_after_seconds == 3.0
        assert str(error) == "HTTP 429 from https://api.zamp.test/actions: Too many requests."

    @pytest.mark.parametrize("header", [None, "", "soon", "-1", "nan", "inf", "Wed, 21 Oct 2015 07:28:00 GMT"])
    async def test_no_usable_wait_is_none(self, header):
        """The platform names no wait when a retry could never fit the limit."""
        headers = {} if header is None else {"Retry-After": header}

        error = await self._refusal(_response(429, _refusal_body(retry_after_seconds=None), headers))

        assert error.retry_after_seconds is None
        assert error.message == _REFUSAL_MESSAGE

    @pytest.mark.parametrize("body", ["[]", "null", json.dumps({"message": "", "details": "x"})])
    async def test_a_body_of_another_shape_is_tolerated(self, body):
        error = await self._refusal(_response(429, body))

        assert error.message == "Too many requests."
        assert error.retry_after_seconds is None

    async def test_a_429_on_a_get_stays_a_plain_http_error(self):
        """Only a POST asks to start something; a 429 on a read is not a refusal to start."""
        client = HttpClient(base_url="https://api.zamp.test")
        with (
            patch("aiohttp.ClientSession", return_value=_session_returning(_response(429, _refusal_body()))),
            pytest.raises(HttpClientError) as exc_info,
        ):
            await client.get("/actions/1")

        assert not isinstance(exc_info.value, RateLimitedError)
        assert exc_info.value.status_code == 429
        assert str(exc_info.value) == "HTTP 429 from https://api.zamp.test/actions/1"

    async def test_other_http_errors_are_not_refusals(self):
        client = HttpClient(base_url="https://api.zamp.test")
        with (
            patch("aiohttp.ClientSession", return_value=_session_returning(_response(503, "unavailable"))),
            pytest.raises(HttpClientError) as exc_info,
        ):
            await client.get("/actions/1")

        assert not isinstance(exc_info.value, RateLimitedError)
        assert str(exc_info.value) == "HTTP 503 from https://api.zamp.test/actions/1"
