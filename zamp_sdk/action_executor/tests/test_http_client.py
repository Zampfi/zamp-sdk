import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zamp_sdk.action_executor.utils import HttpClient, HttpClientError


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


def _response(status: int, body: str) -> AsyncMock:
    response = AsyncMock()
    response.ok = status < 400
    response.status = status
    response.text = AsyncMock(return_value=body)
    return response


# The platform's 429, as its rate limiter renders it.
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
        "details": {"limit_class": "sdk.action", "retry_after_seconds": 2},
    }
)


class TestHttpClientErrorMessage:
    """A non-2xx raises ``HttpClientError`` with the response's own status, and its text adds the
    platform's ``message`` when the body carries one."""

    async def _error(self, response, method: str = "post") -> HttpClientError:
        client = HttpClient(base_url="https://api.zamp.test")
        with (
            patch("aiohttp.ClientSession", return_value=_session_returning(response)),
            pytest.raises(HttpClientError) as exc_info,
        ):
            await getattr(client, method)("/actions")
        return exc_info.value

    async def test_a_429_reads_as_an_http_429_with_the_platform_message(self):
        error = await self._error(_response(429, _REFUSAL_BODY))

        assert error.status_code == 429
        assert str(error) == f"HTTP 429 from https://api.zamp.test/actions: {_REFUSAL_MESSAGE}"
        assert error.message == str(error)
        assert error.response_body == _REFUSAL_BODY

    @pytest.mark.parametrize("status", [400, 403, 404, 500, 503])
    async def test_every_status_keeps_its_own_code(self, status):
        error = await self._error(_response(status, json.dumps({"message": "Not allowed"})), method="get")

        assert error.status_code == status
        assert str(error) == f"HTTP {status} from https://api.zamp.test/actions: Not allowed"

    async def test_the_message_is_trimmed(self):
        error = await self._error(_response(403, json.dumps({"message": "  Not allowed \n"})))

        assert str(error) == "HTTP 403 from https://api.zamp.test/actions: Not allowed"

    @pytest.mark.parametrize(
        "body",
        [
            "<html>Too Many Requests</html>",
            "",
            "[]",
            "null",
            json.dumps({"message": ""}),
            json.dumps({"message": "   "}),
            json.dumps({"message": {"text": "nested"}}),
            json.dumps({"detail": "Not Found"}),
            json.dumps({"error": "Not Found"}),
            "[" * 200_000 + "]" * 200_000,
        ],
    )
    async def test_a_body_without_a_message_keeps_the_plain_text(self, body):
        """A 429 from a proxy in front of the platform, or any body of another shape."""
        error = await self._error(_response(429, body))

        assert error.status_code == 429
        assert str(error) == "HTTP 429 from https://api.zamp.test/actions"
        assert error.response_body == body
