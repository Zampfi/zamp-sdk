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


@evals.external_call("erp.order", key_argument="order_id")
async def fetch_order(order_id: str, realm: str = "prod") -> Order:
    return Order(id=order_id, total=-1)


@evals.external_call("erp.order", key_argument="order_id")
def fetch_order_sync(order_id: str, realm: str = "prod") -> Order:
    return Order(id=order_id, total=-1)


@evals.external_call("erp.status")
async def fetch_status():
    return "live"


@evals.external_call("erp.status")
def fetch_status_sync():
    return "live"


@evals.external_call("erp.page")
async def get_page(url: str) -> httpx.Response:
    return httpx.Response(200)


def sent(execute_action):
    return [call.args[1] for call in execute_action.call_args_list]


class TestOutsideAnEvalTrial:
    async def test_async_runs_untouched(self, execute_action):
        assert await fetch_order("O1") == Order(id="O1", total=-1)

        execute_action.assert_not_called()

    def test_sync_runs_untouched(self, execute_action):
        assert fetch_order_sync("O1") == Order(id="O1", total=-1)

        execute_action.assert_not_called()

    def test_keeps_the_function_name_and_kind(self):
        assert fetch_order.__name__ == "fetch_order"
        assert fetch_order_sync.__name__ == "fetch_order_sync"
        assert inspect.iscoroutinefunction(fetch_order)
        assert not inspect.iscoroutinefunction(fetch_order_sync)


class TestReturns:
    async def test_async_returns_the_fixture_as_the_return_type(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert await fetch_order("O1") == Order(id="O1", total=7)

    def test_sync_returns_the_fixture_as_the_return_type(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_sync_call_inside_a_running_loop(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_without_an_annotation_returns_the_raw_value(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"state": "down"})

        assert await fetch_status() == {"state": "down"}

    async def test_a_field_the_engine_adds_later_is_ignored(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7}) | {"fixture_file": "erp.order.json"}

        assert await fetch_order("O1") == Order(id="O1", total=7)

    async def test_a_human_ask_returns_none(self, in_eval_trial, execute_action, returned):
        @evals.external_call("ask.decision")
        async def ask() -> None: ...

        execute_action.return_value = returned(None)

        assert await ask() is None

    async def test_bytes_are_read_back_from_base64(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.pdf")
        async def fetch_pdf() -> bytes:
            raise NotImplementedError

        execute_action.return_value = returned("JVBERvv_")

        assert await fetch_pdf() == b"%PDF\xfb\xff"

    async def test_bytes_inside_a_return_type_are_read_back_from_base64(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.pdfs")
        async def fetch_pdfs() -> dict[str, list[bytes]]:
            raise NotImplementedError

        execute_action.return_value = returned({"O1": ["JVBERvv_"]})

        assert await fetch_pdfs() == {"O1": [b"%PDF\xfb\xff"]}

    async def test_a_return_type_pydantic_cannot_validate_returns_the_raw_value(
        self, in_eval_trial, execute_action, returned
    ):
        class Session:
            pass

        @evals.external_call("erp.session")
        async def open_session() -> Session:
            raise NotImplementedError

        execute_action.return_value = returned({"id": "s1"})

        assert await open_session() == {"id": "s1"}

    async def test_a_return_type_only_known_to_type_checkers_returns_the_raw_value(
        self, in_eval_trial, execute_action, returned
    ):
        @evals.external_call("erp.total")
        async def fetch_total() -> "Decimal":
            raise NotImplementedError

        execute_action.return_value = returned("12.50")

        assert await fetch_total() == "12.50"


class TestHttpResponse:
    async def test_built_from_status_json_body_and_headers(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"status": 200, "body": {"id": "O1"}, "headers": {"X-Page": "1"}})

        response = await get_page("https://erp.invalid")

        assert (response.status_code, response.json(), response.headers["X-Page"]) == (200, {"id": "O1"}, "1")

    async def test_a_string_body_is_text(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"status": 200, "body": "<html/>"})

        assert (await get_page("https://erp.invalid")).text == "<html/>"

    async def test_content_is_the_decoded_bytes(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"status": 200, "content": base64.b64encode(b"%PDF-1.7").decode()})

        assert (await get_page("https://erp.invalid")).content == b"%PDF-1.7"

    async def test_content_reads_the_url_safe_base64_a_trace_writes(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"status": 200, "content": "JVBERvv_"})

        assert (await get_page("https://erp.invalid")).content == b"%PDF\xfb\xff"

    async def test_a_field_the_response_does_not_know_is_ignored(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"status": 200, "body": {"id": "O1"}, "reason": "OK"})

        assert (await get_page("https://erp.invalid")).json() == {"id": "O1"}

    async def test_an_http_error_raises_on_raise_for_status(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"status": 503, "body": {"error": "busy"}})

        response = await get_page("https://erp.invalid")

        with pytest.raises(httpx.HTTPStatusError, match="503"):
            response.raise_for_status()

    async def test_any_call_name_builds_a_response(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp:fetch")
        async def fetch() -> httpx.Response:
            raise NotImplementedError

        execute_action.return_value = returned({"status": 404})

        with pytest.raises(httpx.HTTPStatusError, match="404"):
            (await fetch()).raise_for_status()

    async def test_an_optional_response(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.maybe")
        async def maybe() -> Optional[httpx.Response]: ...

        execute_action.return_value = returned({"status": 204})
        assert (await maybe()).status_code == 204

        execute_action.return_value = returned(None)
        assert await maybe() is None


class TestRaises:
    async def test_async_raises_what_the_outcome_describes(self, in_eval_trial, execute_action, raised):
        execute_action.return_value = raised("builtins.TimeoutError", "read timed out")

        with pytest.raises(TimeoutError, match="read timed out"):
            await fetch_order("O1")

    def test_sync_raises_what_the_outcome_describes(self, in_eval_trial, execute_action, raised):
        execute_action.return_value = raised("builtins.ConnectionError", "refused")

        with pytest.raises(ConnectionError, match="refused"):
            fetch_order_sync("O1")

    def test_an_sdk_error_type_is_importable(self, in_eval_trial, execute_action, raised):
        execute_action.return_value = raised("zamp_sdk.AgentDbError", "boom")

        with pytest.raises(AgentDbError, match="boom"):
            fetch_order_sync("O1")

    async def test_an_httpx_transport_error(self, in_eval_trial, execute_action, raised):
        execute_action.return_value = raised("httpx.ConnectTimeout", "timed out")

        with pytest.raises(httpx.ConnectTimeout, match="timed out"):
            await get_page("https://erp.invalid")

    async def test_a_fixture_failure_raises_fixture_lookup_error_with_the_engine_message(
        self, in_eval_trial, execute_action, fixture_lookup_failed
    ):
        execute_action.return_value = fixture_lookup_failed(
            "FIXTURE_EXHAUSTED", "erp.order:O1#3: the fixture list for this call ran out"
        )

        with pytest.raises(evals.FixtureLookupError, match="^erp.order:O1#3: the fixture list for this call ran out$"):
            await fetch_order("O1")

    def test_a_sync_fixture_failure_raises_fixture_lookup_error(
        self, in_eval_trial, execute_action, fixture_lookup_failed
    ):
        execute_action.return_value = fixture_lookup_failed("FIXTURE_MISSING", "erp.status#1: no fixture")

        with pytest.raises(evals.FixtureLookupError, match="^erp.status#1: no fixture$"):
            fetch_status_sync()

    async def test_a_failed_request_propagates(self, in_eval_trial, execute_action):
        execute_action.side_effect = RuntimeError("Action eval_external_call FAILED")

        with pytest.raises(RuntimeError, match="eval_external_call"):
            await fetch_order("O1")


class TestRequest:
    async def test_async_sends_the_call(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        await fetch_order("O1")

        action, call = execute_action.call_args.args
        assert action == "eval_external_call"
        assert execute_action.call_args.kwargs == {}
        assert call == {
            "invocation_id": call["invocation_id"],
            "name": "erp.order",
            "key": "O1",
            "parent": "test_external.py:test_async_sends_the_call",
            "args": {"order_id": "O1", "realm": "prod"},
        }

    def test_sync_sends_arguments_by_name(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        fetch_order_sync(realm="test", order_id="O1")

        (call,) = sent(execute_action)
        assert call["args"] == {"order_id": "O1", "realm": "test"}
        assert call["parent"] == "test_external.py:test_sync_sends_arguments_by_name"

    async def test_parallel_calls_name_their_caller(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        await asyncio.gather(fetch_order("O1"), fetch_order("O2"))

        assert {call["parent"] for call in sent(execute_action)} == {
            "test_external.py:test_parallel_calls_name_their_caller"
        }

    def test_no_key_sends_none(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned("down")

        fetch_status_sync()

        assert sent(execute_action)[0]["key"] is None

    def test_an_integer_key_is_sent_as_text(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.page", key_argument="page")
        def get_page_number(page: int): ...

        execute_action.return_value = returned(None)
        get_page_number(2)

        assert sent(execute_action)[0]["key"] == "2"

    def test_any_name_and_key_are_sent_as_written(self, in_eval_trial, execute_action, returned):
        name = f"Mail.Fetch_{'x' * 100}"

        @evals.external_call(name, key_argument="file_name")
        def fetch_attachment(file_name: str): ...

        execute_action.return_value = returned(None)
        fetch_attachment("notes #2.msg")

        (call,) = sent(execute_action)
        assert (call["name"], call["key"]) == (name, "notes #2.msg")

    def test_a_keyword_named_like_a_positional_only_parameter_keeps_the_key(
        self, in_eval_trial, execute_action, returned
    ):
        @evals.external_call("erp.order", key_argument="order_id")
        def fetch(order_id: str, /, **kwargs): ...

        execute_action.return_value = returned(None)
        fetch("O1", order_id="meta")

        assert sent(execute_action)[0]["key"] == "O1"

    def test_secret_arguments_are_never_sent(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.token")
        def fetch_token(url: str, headers: dict, auth: str, token: str, credentials: dict): ...

        execute_action.return_value = returned(None)
        fetch_token("https://erp.invalid", {"Authorization": "Bearer x"}, "basic", "t0k", {"id": "c1"})

        assert sent(execute_action)[0]["args"] == {"url": "https://erp.invalid"}

    def test_secret_arguments_passed_through_kwargs_are_never_sent(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.request")
        def request(method: str, url: str, **kwargs): ...

        execute_action.return_value = returned(None)
        request("GET", "https://erp.invalid", headers={"Authorization": "Bearer x"}, token="t0k", timeout=5)

        assert sent(execute_action)[0]["args"] == {"method": "GET", "url": "https://erp.invalid", "timeout": 5}

    def test_arguments_named_like_a_credential_are_never_sent(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.login")
        def login(url: str, api_key: str, Password: str, client_secret: str, **kwargs): ...

        execute_action.return_value = returned(None)
        login("https://erp.invalid", "k1", "p1", "cs1", Authorization="Bearer x", refresh_token="t0k", page=2)

        assert sent(execute_action)[0]["args"] == {"url": "https://erp.invalid", "page": 2}

    def test_only_whole_credential_names_are_left_out(self, in_eval_trial, execute_action, returned):
        @evals.external_call("llm.complete")
        def complete(**kwargs): ...

        kept = ["max_tokens", "keys", "key", "sort_key", "keyword", "secretary", "authorization_id"]
        dropped = ["access_token", "x_api_key", "db_password", "extra_headers", "cookie", "pwd"]
        execute_action.return_value = returned(None)
        complete(**{name: 1 for name in kept + dropped})

        assert sent(execute_action)[0]["args"] == {name: 1 for name in kept}

    async def test_a_method_never_sends_its_instance(self, in_eval_trial, execute_action, returned):
        class Client:
            def __init__(self, token: str):
                self.token = token

            @evals.external_call("erp.order", key_argument="order_id")
            async def fetch(self, order_id: str) -> dict:
                return {}

            @classmethod
            @evals.external_call("erp.status")
            def status(cls, realm: str) -> str:
                return "live"

        execute_action.return_value = returned({})
        await Client("t0k").fetch("O1")
        execute_action.return_value = returned("live")
        Client.status("prod")

        assert [call["args"] for call in sent(execute_action)] == [{"order_id": "O1"}, {"realm": "prod"}]

    def test_an_argument_json_cannot_hold_is_sent_as_its_repr(self, in_eval_trial, execute_action, returned):
        class Session:
            def __repr__(self):
                return "<Session>"

        @evals.external_call("erp.post")
        def post(session: Session, order: Order): ...

        execute_action.return_value = returned(None)
        post(Session(), Order(id="O1", total=7))

        assert sent(execute_action)[0]["args"] == {"session": "<Session>", "order": {"id": "O1", "total": 7}}

    def test_an_argument_that_contains_itself_is_sent_as_its_repr(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.post")
        def post(lines: list, page: int): ...

        lines: list = []
        lines.append(lines)
        execute_action.return_value = returned(None)
        post(lines, 2)

        assert sent(execute_action)[0]["args"] == {"lines": "[[...]]", "page": 2}

    def test_bytes_are_sent_as_base64(self, in_eval_trial, execute_action, returned):
        @evals.external_call("erp.upload")
        def upload(name: bytes, content: bytes): ...

        execute_action.return_value = returned(None)
        upload(b"invoice.pdf", b"%PDF\xff")

        assert sent(execute_action)[0]["args"] == {"name": "aW52b2ljZS5wZGY=", "content": "JVBERv8="}

    def test_every_call_has_its_own_invocation_id(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned("down")

        fetch_status_sync()
        fetch_status_sync()

        first, second = (call["invocation_id"] for call in sent(execute_action))
        assert first != second


class TestOnTheExecutor:
    async def test_async_reads_the_bound_id_through_the_action_response(
        self, in_eval_trial_on_actions_hub, execute_action, returned, action_response
    ):
        execute_action.return_value = action_response(returned({"id": "O1", "total": 7}))

        assert await fetch_order("O1") == Order(id="O1", total=7)
        assert sent(execute_action)[0]["invocation_id"] == "workflow-uuid"

    async def test_a_fixture_failure_raises_fixture_lookup_error(
        self, in_eval_trial_on_actions_hub, execute_action, fixture_lookup_failed, action_response
    ):
        execute_action.return_value = action_response(
            fixture_lookup_failed("FIXTURE_MISSING", "erp.order:O1#1: no fixture")
        )

        with pytest.raises(evals.FixtureLookupError, match="^erp.order:O1#1: no fixture$"):
            await fetch_order("O1")

    async def test_a_failed_action_raises(self, in_eval_trial_on_actions_hub, execute_action, action_response):
        execute_action.return_value = action_response(status="FAILED", error="no eval run")

        with pytest.raises(RuntimeError, match="^eval_external_call action-1 FAILED: no eval run$"):
            await fetch_order("O1")

    def test_sync_runs_untouched_outside_a_trial(self, on_actions_hub_outside_a_trial, execute_action):
        assert fetch_order_sync("O1") == Order(id="O1", total=-1)

        execute_action.assert_not_called()

    def test_sync_refuses_in_workflow_code(self, in_eval_trial_on_actions_hub, execute_action):
        with pytest.raises(RuntimeError, match="^erp.order: a sync function .* make fetch_order_sync async$"):
            fetch_order_sync("O1")

        execute_action.assert_not_called()


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

    async def test_a_request_is_never_logged_or_captured(self, in_eval_trial, returned):
        configure_auto_action_logs(True)
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = returned({"id": "O1", "total": 7})
            await fetch_order("O1")

        assert drain_log_capture() == []
        assert [call.kwargs["action_name"] for call in run.call_args_list] == ["eval_external_call"]

    async def test_an_ordinary_action_in_the_same_setup_is_logged(self, in_eval_trial):
        configure_auto_action_logs(True)
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = {"ok": True}
            await ActionExecutor.execute("do_thing", {"a": 1})

        assert [entry["event"] for entry in drain_log_capture()] == ["action"]
        assert "emit_log" in [call.kwargs["action_name"] for call in run.call_args_list]
