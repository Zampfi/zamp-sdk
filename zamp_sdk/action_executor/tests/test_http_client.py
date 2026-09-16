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


def _session_answering(*, ok: bool, status: int, text: str) -> AsyncMock:
    response = AsyncMock()
    response.ok = ok
    response.status = status
    response.text = AsyncMock(return_value=text)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session.request = MagicMock(return_value=ctx)
    return session


class TestHttpClientActionDocuments:
    """An inline POST answers with an action document whose ``error`` is the action's
    own failure message, not the response envelope's."""

    async def test_the_envelope_error_check_can_be_switched_off(self):
        client = HttpClient(base_url="https://api.zamp.test")
        document = {"id": "a", "status": "FAILED", "result": None, "error": "statement 1 failed"}
        session = _session_answering(ok=True, status=200, text=json.dumps(document))

        with patch("aiohttp.ClientSession", return_value=session):
            result = await client.post("/actions", data={}, raise_on_envelope_error=False)

        assert result == document

    async def test_the_envelope_error_check_is_on_by_default(self):
        client = HttpClient(base_url="https://api.zamp.test")
        document = {"id": "a", "status": "FAILED", "result": None, "error": "statement 1 failed"}
        session = _session_answering(ok=True, status=200, text=json.dumps(document))

        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(HttpClientError, match="statement 1 failed"),
        ):
            await client.post("/actions", data={})

    async def test_the_timeout_is_passed_per_request(self):
        client = HttpClient(base_url="https://api.zamp.test", timeout=30)
        session = _session_answering(ok=True, status=200, text=json.dumps({"id": "a"}))

        with (
            patch("aiohttp.ClientSession", return_value=session),
            patch("zamp_sdk.action_executor.utils.http_client.aiohttp.ClientTimeout") as timeout_cls,
        ):
            await client.post("/actions", data={}, timeout=12.5)

        timeout_cls.assert_called_once_with(total=12.5)


class TestHttpClientErrorMessages:
    """A 4xx carries the platform's sentence, which is the caller's only explanation."""

    async def test_a_flat_platform_error_message_is_surfaced(self):
        client = HttpClient(base_url="https://api.zamp.test")
        body = {"code": "VALIDATION_FAILED", "message": "Action 'x' cannot run inline: it is a workflow"}
        session = _session_answering(ok=False, status=400, text=json.dumps(body))

        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(HttpClientError, match="HTTP 400 .*: Action 'x' cannot run inline: it is a workflow") as exc,
        ):
            await client.post("/actions", data={})

        assert exc.value.status_code == 400
        assert exc.value.response_body == json.dumps(body)

    async def test_a_wrapped_error_message_is_surfaced(self):
        client = HttpClient(base_url="https://api.zamp.test")
        session = _session_answering(ok=False, status=403, text=json.dumps({"error": {"message": "no access"}}))

        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(HttpClientError, match="HTTP 403 .*: no access"),
        ):
            await client.get("/actions/a")

    async def test_a_non_json_body_keeps_the_generic_message(self):
        client = HttpClient(base_url="https://api.zamp.test")
        session = _session_answering(ok=False, status=502, text="Bad Gateway")

        with (
            patch("aiohttp.ClientSession", return_value=session),
            pytest.raises(HttpClientError) as exc,
        ):
            await client.get("/actions/a")

        assert str(exc.value) == "HTTP 502 from https://api.zamp.test/actions/a"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ('{"message": "flat"}', "flat"),
            ('{"error": {"message": "wrapped"}}', "wrapped"),
            ('{"error": "bare"}', "bare"),
            ('{"detail": "framework"}', "framework"),
            ('{"detail": [{"loc": ["body"]}]}', None),
            ('{"error": {"code": "X"}}', None),
            ("[]", None),
            ("not json", None),
        ],
    )
    def test_server_message_shapes(self, text, expected):
        assert HttpClient._server_message(text) == expected
