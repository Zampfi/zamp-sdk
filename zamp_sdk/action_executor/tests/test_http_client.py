import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zamp_sdk.action_executor.utils import HttpClient, HttpClientError, RateLimitedError
from zamp_sdk.version import __version__


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


# The platform's 429, as the rate limiter's handler renders it.
_REFUSAL_MESSAGE = (
    "Your organization is using SDK actions faster than its limit (120 per minute). This request was NOT "
    "started. Wait 2 s before retrying; do not retry in a loop or in parallel. If you need a higher limit, "
    "contact support."
)
_REFUSAL_BODY = json.dumps(
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
            "retry_after_seconds": 2,
        },
    }
)


class TestHttpClientRateLimited:
    async def _refusal(self, response) -> RateLimitedError:
        client = HttpClient(base_url="https://api.zamp.test")
        with (
            patch("aiohttp.ClientSession", return_value=_session_returning(response)),
            pytest.raises(RateLimitedError) as exc_info,
        ):
            await client.post("/actions", data={"action_name": "x"})
        return exc_info.value

    async def test_a_429_is_a_typed_refusal_carrying_the_platform_text(self):
        error = await self._refusal(_response(429, _REFUSAL_BODY, {"Retry-After": "2", "Cache-Control": "no-store"}))

        assert error.message == _REFUSAL_MESSAGE
        assert error.retry_after == 2.0
        assert error.check == "org"
        assert error.limit_class == "sdk.action"
        assert error.status_code == 429
        assert error.response_body == _REFUSAL_BODY

    async def test_existing_http_error_handlers_still_catch_it(self):
        error = await self._refusal(_response(429, _REFUSAL_BODY, {"Retry-After": "2"}))

        assert isinstance(error, HttpClientError)
        # Agent prompts written for SDK 1.2 key on this text, so it still leads.
        assert str(error).startswith("HTTP 429 from https://api.zamp.test/actions")
        assert _REFUSAL_MESSAGE in str(error)

    async def test_its_repr_carries_the_same_text(self):
        """A script that prints the error with ``!r`` still shows ``HTTP 429``, as with SDK 1.2."""
        error = await self._refusal(_response(429, _REFUSAL_BODY, {"Retry-After": "2"}))

        assert repr(error) == f"RateLimitedError({str(error)!r})"
        assert "HTTP 429 from https://api.zamp.test/actions" in repr(error)

    def test_an_in_band_refusal_reprs_with_its_prefix(self):
        error = RateLimitedError("over the limit", status_code=None)

        assert repr(error) == "RateLimitedError('RATE_LIMITED: over the limit')"

    async def test_the_body_gives_the_wait_when_the_header_is_missing(self):
        error = await self._refusal(_response(429, _REFUSAL_BODY))

        assert error.retry_after == 2.0

    async def test_the_header_wins_over_the_body(self):
        error = await self._refusal(_response(429, _REFUSAL_BODY, {"Retry-After": "5"}))

        assert error.retry_after == 5.0

    @pytest.mark.parametrize("header", ["soon", "-1", "nan", "inf", ""])
    async def test_an_unusable_header_falls_back_to_the_body(self, header):
        error = await self._refusal(_response(429, _REFUSAL_BODY, {"Retry-After": header}))

        assert error.retry_after == 2.0

    async def test_no_wait_anywhere_is_none(self):
        """The platform leaves both out when a retry could never fit the limit."""
        body = json.loads(_REFUSAL_BODY)
        body["details"]["retry_after_seconds"] = None

        error = await self._refusal(_response(429, json.dumps(body)))

        assert error.retry_after is None
        assert error.check == "org"

    async def test_a_429_from_in_front_of_the_platform_is_still_typed(self):
        """A proxy's 429 has no JSON body: still a RateLimitedError, with what it did say."""
        error = await self._refusal(_response(429, "<html>Too Many Requests</html>", {"Retry-After": "3"}))

        assert error.retry_after == 3.0
        assert error.check is None
        assert error.limit_class is None
        assert error.message == "Too many requests."
        assert str(error) == "HTTP 429 from https://api.zamp.test/actions: Too many requests."

    async def test_other_http_errors_are_not_refusals(self):
        client = HttpClient(base_url="https://api.zamp.test")
        with (
            patch("aiohttp.ClientSession", return_value=_session_returning(_response(503, "unavailable"))),
            pytest.raises(HttpClientError) as exc_info,
        ):
            await client.get("/actions/1")

        assert not isinstance(exc_info.value, RateLimitedError)
        assert exc_info.value.status_code == 503


class TestHttpClientUserAgent:
    @pytest.mark.parametrize("method", ["get", "post"])
    async def test_every_request_names_the_sdk_version(self, method):
        client = HttpClient(base_url="https://api.zamp.test", default_headers={"Authorization": "Bearer t"})
        session = _session_returning(_response(200, json.dumps({"id": "1"})))

        with patch("aiohttp.ClientSession", return_value=session):
            await getattr(client, method)("/actions")

        headers = session.request.call_args.kwargs["headers"]
        assert headers["User-Agent"] == f"zamp-sdk/{__version__}"
        assert headers["Authorization"] == "Bearer t"
