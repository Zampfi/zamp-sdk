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
