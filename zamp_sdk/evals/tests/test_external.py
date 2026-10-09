import asyncio
import base64
import inspect
from typing import TYPE_CHECKING, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import BaseModel

from zamp_sdk import AgentDbError, configure_auto_action_logs, evals
from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.capture import drain_log_capture, start_log_capture

if TYPE_CHECKING:
    from decimal import Decimal


class Order(BaseModel):
    id: str
    total: int


@evals.external("erp.order", key="order_id")
async def fetch_order(order_id: str, realm: str = "prod") -> Order:
    return Order(id=order_id, total=-1)


@evals.external("erp.order", key="order_id")
def fetch_order_sync(order_id: str, realm: str = "prod") -> Order:
    return Order(id=order_id, total=-1)


@evals.external("erp.status")
async def fetch_status():
    return "live"


@evals.external("erp.status")
def fetch_status_sync():
    return "live"


@evals.external("erp.page")
async def get_page(url: str) -> httpx.Response:
    return httpx.Response(200)


def sent(fixtures_and_trace):
    return [call.args[1] for call in fixtures_and_trace.call_args_list]


class TestOutsideAnEvalRun:
    async def test_async_runs_untouched(self, fixtures_and_trace):
        assert await fetch_order("O1") == Order(id="O1", total=-1)

        fixtures_and_trace.assert_not_called()

    def test_sync_runs_untouched(self, fixtures_and_trace):
        assert fetch_order_sync("O1") == Order(id="O1", total=-1)

        fixtures_and_trace.assert_not_called()

    def test_keeps_the_function_name_and_kind(self):
        assert fetch_order.__name__ == "fetch_order"
        assert fetch_order_sync.__name__ == "fetch_order_sync"
        assert inspect.iscoroutinefunction(fetch_order)
        assert not inspect.iscoroutinefunction(fetch_order_sync)


class TestReturns:
    async def test_async_returns_the_fixture_as_the_return_type(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"id": "O1", "total": 7})

        assert await fetch_order("O1") == Order(id="O1", total=7)

    def test_sync_returns_the_fixture_as_the_return_type(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_sync_call_inside_a_running_loop(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_without_an_annotation_returns_the_raw_value(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"state": "down"})

        assert await fetch_status() == {"state": "down"}

    async def test_a_human_ask_returns_none(self, eval_run, fixtures_and_trace, returned):
        @evals.external("ask.decision")
        async def ask() -> None: ...

        fixtures_and_trace.return_value = returned(None)

        assert await ask() is None

    async def test_a_return_type_only_known_to_type_checkers_returns_the_raw_value(
        self, eval_run, fixtures_and_trace, returned
    ):
        @evals.external("erp.total")
        async def fetch_total() -> "Decimal":
            raise NotImplementedError

        fixtures_and_trace.return_value = returned("12.50")

        assert await fetch_total() == "12.50"


class TestHttpResponse:
    async def test_built_from_status_json_body_and_headers(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"status": 200, "body": {"id": "O1"}, "headers": {"X-Page": "1"}})

        response = await get_page("https://erp.invalid")

        assert (response.status_code, response.json(), response.headers["X-Page"]) == (200, {"id": "O1"}, "1")

    async def test_a_string_body_is_text(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"status": 200, "body": "<html/>"})

        assert (await get_page("https://erp.invalid")).text == "<html/>"

    async def test_content_is_the_decoded_bytes(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"status": 200, "content": base64.b64encode(b"%PDF-1.7").decode()})

        assert (await get_page("https://erp.invalid")).content == b"%PDF-1.7"

    async def test_an_http_error_raises_on_raise_for_status(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"status": 503, "body": {"error": "busy"}})

        response = await get_page("https://erp.invalid")

        with pytest.raises(httpx.HTTPStatusError, match="503"):
            response.raise_for_status()

    async def test_an_optional_response(self, eval_run, fixtures_and_trace, returned):
        @evals.external("erp.maybe")
        async def maybe() -> Optional[httpx.Response]: ...

        fixtures_and_trace.return_value = returned({"status": 204})
        assert (await maybe()).status_code == 204

        fixtures_and_trace.return_value = returned(None)
        assert await maybe() is None


class TestRaises:
    async def test_async_raises_what_the_outcome_describes(self, eval_run, fixtures_and_trace, raised):
        fixtures_and_trace.return_value = raised("builtins.TimeoutError", "read timed out")

        with pytest.raises(TimeoutError, match="read timed out"):
            await fetch_order("O1")

    def test_sync_raises_what_the_outcome_describes(self, eval_run, fixtures_and_trace, raised):
        fixtures_and_trace.return_value = raised("builtins.ConnectionError", "refused")

        with pytest.raises(ConnectionError, match="refused"):
            fetch_order_sync("O1")

    def test_an_sdk_error_type_is_importable(self, eval_run, fixtures_and_trace, raised):
        fixtures_and_trace.return_value = raised("zamp_sdk.AgentDbError", "boom")

        with pytest.raises(AgentDbError, match="boom"):
            fetch_order_sync("O1")

    async def test_an_httpx_transport_error(self, eval_run, fixtures_and_trace, raised):
        fixtures_and_trace.return_value = raised("httpx.ConnectTimeout", "timed out")

        with pytest.raises(httpx.ConnectTimeout, match="timed out"):
            await get_page("https://erp.invalid")

    async def test_a_fixture_failure_raises_fixture_error_with_the_engine_message(
        self, eval_run, fixtures_and_trace, fixture_failed
    ):
        fixtures_and_trace.return_value = fixture_failed(
            "FIXTURE_EXHAUSTED", "erp.order:O1#3: the fixture list for this call ran out"
        )

        with pytest.raises(evals.FixtureError, match="^erp.order:O1#3: the fixture list for this call ran out$"):
            await fetch_order("O1")

    def test_a_sync_fixture_failure_raises_fixture_error(self, eval_run, fixtures_and_trace, fixture_failed):
        fixtures_and_trace.return_value = fixture_failed("FIXTURE_MISSING", "erp.status#1: no fixture")

        with pytest.raises(evals.FixtureError, match="^erp.status#1: no fixture$"):
            fetch_status_sync()

    async def test_a_failed_request_propagates(self, eval_run, fixtures_and_trace):
        fixtures_and_trace.side_effect = RuntimeError("Action eval_external_call FAILED")

        with pytest.raises(RuntimeError, match="eval_external_call"):
            await fetch_order("O1")


class TestRequest:
    async def test_async_sends_the_call(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"id": "O1", "total": 7})

        await fetch_order("O1")

        action, call = fixtures_and_trace.call_args.args
        assert action == "eval_external_call"
        assert fixtures_and_trace.call_args.kwargs == {}
        assert call == {
            "invocation_id": call["invocation_id"],
            "name": "erp.order",
            "key": "O1",
            "parent": "test_external.py:test_async_sends_the_call",
            "args": {"order_id": "O1", "realm": "prod"},
        }

    def test_sync_sends_arguments_by_name(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"id": "O1", "total": 7})

        fetch_order_sync(realm="test", order_id="O1")

        (call,) = sent(fixtures_and_trace)
        assert call["args"] == {"order_id": "O1", "realm": "test"}
        assert call["parent"] == "test_external.py:test_sync_sends_arguments_by_name"

    async def test_parallel_calls_name_their_caller(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned({"id": "O1", "total": 7})

        await asyncio.gather(fetch_order("O1"), fetch_order("O2"))

        assert {call["parent"] for call in sent(fixtures_and_trace)} == {
            "test_external.py:test_parallel_calls_name_their_caller"
        }

    def test_no_key_sends_none(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned("down")

        fetch_status_sync()

        assert sent(fixtures_and_trace)[0]["key"] is None

    def test_an_integer_key_is_sent_as_text(self, eval_run, fixtures_and_trace, returned):
        @evals.external("erp.page", key="page")
        def get_page_number(page: int): ...

        fixtures_and_trace.return_value = returned(None)
        get_page_number(2)

        assert sent(fixtures_and_trace)[0]["key"] == "2"

    def test_secret_arguments_are_never_sent(self, eval_run, fixtures_and_trace, returned):
        @evals.external("erp.token")
        def fetch_token(url: str, headers: dict, auth: str, token: str, credentials: dict): ...

        fixtures_and_trace.return_value = returned(None)
        fetch_token("https://erp.invalid", {"Authorization": "Bearer x"}, "basic", "t0k", {"id": "c1"})

        assert sent(fixtures_and_trace)[0]["args"] == {"url": "https://erp.invalid"}

    def test_secret_arguments_passed_through_kwargs_are_never_sent(self, eval_run, fixtures_and_trace, returned):
        @evals.external("erp.request")
        def request(method: str, url: str, **kwargs): ...

        fixtures_and_trace.return_value = returned(None)
        request("GET", "https://erp.invalid", headers={"Authorization": "Bearer x"}, token="t0k", timeout=5)

        assert sent(fixtures_and_trace)[0]["args"] == {"method": "GET", "url": "https://erp.invalid", "timeout": 5}

    async def test_a_method_never_sends_its_instance(self, eval_run, fixtures_and_trace, returned):
        class Client:
            def __init__(self, token: str):
                self.token = token

            @evals.external("erp.order", key="order_id")
            async def fetch(self, order_id: str) -> dict:
                return {}

            @classmethod
            @evals.external("erp.status")
            def status(cls, realm: str) -> str:
                return "live"

        fixtures_and_trace.return_value = returned({})
        await Client("t0k").fetch("O1")
        fixtures_and_trace.return_value = returned("live")
        Client.status("prod")

        assert [call["args"] for call in sent(fixtures_and_trace)] == [{"order_id": "O1"}, {"realm": "prod"}]

    def test_an_argument_json_cannot_hold_is_sent_as_its_repr(self, eval_run, fixtures_and_trace, returned):
        class Session:
            def __repr__(self):
                return "<Session>"

        @evals.external("erp.post")
        def post(session: Session, order: Order): ...

        fixtures_and_trace.return_value = returned(None)
        post(Session(), Order(id="O1", total=7))

        assert sent(fixtures_and_trace)[0]["args"] == {"session": "<Session>", "order": {"id": "O1", "total": 7}}

    def test_bytes_are_sent_as_base64(self, eval_run, fixtures_and_trace, returned):
        @evals.external("erp.upload")
        def upload(name: bytes, content: bytes): ...

        fixtures_and_trace.return_value = returned(None)
        upload(b"invoice.pdf", b"%PDF\xff")

        assert sent(fixtures_and_trace)[0]["args"] == {"name": "aW52b2ljZS5wZGY=", "content": "JVBERv8="}

    def test_every_call_has_its_own_invocation_id(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.return_value = returned("down")

        fetch_status_sync()
        fetch_status_sync()

        first, second = (call["invocation_id"] for call in sent(fixtures_and_trace))
        assert first != second


class TestOnTheExecutor:
    async def test_async_reads_the_bound_id_through_the_gateway_envelope(
        self, executor_eval_run, fixtures_and_trace, returned, envelope
    ):
        fixtures_and_trace.return_value = envelope(returned({"id": "O1", "total": 7}))

        assert await fetch_order("O1") == Order(id="O1", total=7)
        assert sent(fixtures_and_trace)[0]["invocation_id"] == "workflow-uuid"

    async def test_a_fixture_failure_raises_fixture_error(
        self, executor_eval_run, fixtures_and_trace, fixture_failed, envelope
    ):
        fixtures_and_trace.return_value = envelope(fixture_failed("FIXTURE_MISSING", "erp.order:O1#1: no fixture"))

        with pytest.raises(evals.FixtureError, match="^erp.order:O1#1: no fixture$"):
            await fetch_order("O1")

    async def test_a_failed_action_raises(self, executor_eval_run, fixtures_and_trace, envelope):
        fixtures_and_trace.return_value = envelope(status="FAILED", error="no eval run")

        with pytest.raises(RuntimeError, match="^eval_external_call action-1 FAILED: no eval run$"):
            await fetch_order("O1")

    def test_sync_refuses_in_workflow_code(self, executor_eval_run, fixtures_and_trace):
        with pytest.raises(RuntimeError, match="erp.order: a sync function cannot reach eval_external_call"):
            fetch_order_sync("O1")

        fixtures_and_trace.assert_not_called()


class TestTheActionLeavesNoTrace:
    @pytest.fixture(autouse=True)
    def _runtime_env(self, monkeypatch):
        monkeypatch.setenv("ZAMP_BASE_URL", "https://example.invalid")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "token")
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "conversation")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "11111111-1111-1111-1111-111111111111")
        monkeypatch.setenv("ZAMP_STREAMING_ID", "s")
        monkeypatch.setenv("ZAMP_MESSAGE_ID", "m")
        monkeypatch.setenv("ZAMP_TOOL_CALL_ID", "t")
        monkeypatch.setenv("ZAMP_RUN_ID", "r")

    async def test_a_request_is_never_logged_or_captured(self, eval_run, returned):
        configure_auto_action_logs(True)
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = returned({"id": "O1", "total": 7})
            await fetch_order("O1")

        assert drain_log_capture() == []
        assert [call.kwargs["action_name"] for call in run.call_args_list] == ["eval_external_call"]

    async def test_an_ordinary_action_in_the_same_setup_is_logged(self, eval_run):
        configure_auto_action_logs(True)
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = {"ok": True}
            await ActionExecutor.execute("do_thing", {"a": 1})

        assert [entry["event"] for entry in drain_log_capture()] == ["action"]
        assert "emit_log" in [call.kwargs["action_name"] for call in run.call_args_list]
