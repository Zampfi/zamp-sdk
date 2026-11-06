import base64
import inspect
import sys
import types
from typing import TYPE_CHECKING, Annotated, Literal, Optional, TypedDict
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from conftest import drained_steps
from zamp_sdk import AgentDbError, configure_auto_action_logs, mocks
from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.capture import start_log_capture
from zamp_sdk.mocks import mockable
from zamp_sdk.mocks.models import MockHttpResponse

if TYPE_CHECKING:
    from decimal import Decimal


class Order(BaseModel):
    id: str
    total: int


@mockable("erp.order")
async def fetch_order(order_id: str, realm: str = "prod") -> Order:
    return Order(id=order_id, total=-1)


@mockable("erp.order")
def fetch_order_sync(order_id: str, realm: str = "prod") -> Order:
    return Order(id=order_id, total=-1)


@mockable("erp.status")
async def fetch_status():
    return "live"


@mockable("erp.status")
def fetch_status_sync():
    return "live"


@mockable("erp.page")
async def get_page(url: str) -> httpx.Response:
    return httpx.Response(200)


def sent(execute_action):
    return [call.args[1] for call in execute_action.call_args_list]


SKILL_CODE = """
class OrderLockedError(Exception):
    pass

@mockable("erp.cancel")
async def cancel_order(order_id: str) -> None:
    raise OrderLockedError(order_id)
"""


def _exec_skill_code():
    skill_globals = {"__name__": "skill_code_run_by_exec", "mockable": mockable}
    exec(SKILL_CODE, skill_globals)
    return skill_globals


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
    async def test_async_returns_the_mock_as_the_return_type(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert await fetch_order("O1") == Order(id="O1", total=7)

    def test_sync_returns_the_mock_as_the_return_type(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_sync_call_inside_a_running_loop(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_without_an_annotation_returns_the_raw_value(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"state": "down"})

        assert await fetch_status() == {"state": "down"}

    async def test_a_field_the_engine_adds_later_is_ignored(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7}) | {"mock_file": "erp.order.json"}

        assert await fetch_order("O1") == Order(id="O1", total=7)

    async def test_a_human_ask_returns_none(self, in_eval_trial, execute_action, returned):
        @mockable("ask.decision")
        async def ask() -> None: ...

        execute_action.return_value = returned(None)

        assert await ask() is None

    async def test_bytes_are_read_back_from_base64(self, in_eval_trial, execute_action, returned):
        @mockable("erp.pdf")
        async def fetch_pdf() -> bytes:
            raise NotImplementedError

        execute_action.return_value = returned("JVBERvv_")

        assert await fetch_pdf() == b"%PDF\xfb\xff"

    async def test_bytes_inside_a_return_type_are_read_back_from_base64(self, in_eval_trial, execute_action, returned):
        @mockable("erp.pdfs")
        async def fetch_pdfs() -> dict[str, list[bytes]]:
            raise NotImplementedError

        execute_action.return_value = returned({"O1": ["JVBERvv_"]})

        assert await fetch_pdfs() == {"O1": [b"%PDF\xfb\xff"]}

    async def test_an_annotated_model_is_returned_as_the_model(self, in_eval_trial, execute_action, returned):
        @mockable("erp.order")
        async def fetch() -> Annotated[Order, Field(description="the order")]:
            raise NotImplementedError

        execute_action.return_value = returned({"id": "O1", "total": 5})

        assert await fetch() == Order(id="O1", total=5)

    async def test_an_annotated_typed_dict_is_returned_as_the_dict(self, in_eval_trial, execute_action, returned):
        class Invoice(TypedDict):
            id: str

        @mockable("erp.invoice")
        async def fetch() -> Annotated[Invoice, Field(description="the invoice")]:
            raise NotImplementedError

        execute_action.return_value = returned({"id": "I1"})

        assert await fetch() == {"id": "I1"}

    async def test_a_return_type_pydantic_cannot_validate_returns_the_raw_value(
        self, in_eval_trial, execute_action, returned
    ):
        class Session:
            pass

        @mockable("erp.session")
        async def open_session() -> Session:
            raise NotImplementedError

        execute_action.return_value = returned({"id": "s1"})

        assert await open_session() == {"id": "s1"}

    async def test_an_unresolvable_parameter_annotation_keeps_the_return_type(
        self, in_eval_trial, execute_action, returned
    ):
        @mockable("erp.order")
        async def fetch(client: "Decimal") -> Order:
            raise NotImplementedError

        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert await fetch(None) == Order(id="O1", total=7)

    async def test_a_string_return_annotation_is_evaluated_off_the_executor(
        self, in_eval_trial, execute_action, returned
    ):
        @mockable("erp.order")
        async def fetch() -> "Order":
            raise NotImplementedError

        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert await fetch() == Order(id="O1", total=7)

    async def test_a_return_type_only_known_to_type_checkers_returns_the_raw_value(
        self, in_eval_trial, execute_action, returned
    ):
        @mockable("erp.total")
        async def fetch_total() -> "Decimal":
            raise NotImplementedError

        execute_action.return_value = returned("12.50")

        assert await fetch_total() == "12.50"

    async def test_the_signature_and_return_type_are_read_once_per_function(
        self, in_eval_trial, execute_action, returned
    ):
        execute_action.return_value = returned({"id": "O1"})
        with (
            patch("inspect.signature", wraps=inspect.signature) as read_signature,
            patch("zamp_sdk.mocks.utils.outcomes.TypeAdapter", wraps=TypeAdapter) as build_adapter,
        ):

            @mockable("erp.order")
            async def fetch(order_id: str) -> dict:
                raise NotImplementedError

            await fetch("O1")
            await fetch("O2")

        assert read_signature.call_count == 1
        build_adapter.assert_called_once()


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
        @mockable("erp:fetch")
        async def fetch() -> httpx.Response:
            raise NotImplementedError

        execute_action.return_value = returned({"status": 404})

        with pytest.raises(httpx.HTTPStatusError, match="404"):
            (await fetch()).raise_for_status()

    async def test_an_optional_response(self, in_eval_trial, execute_action, returned):
        @mockable("erp.maybe")
        async def maybe() -> Optional[httpx.Response]: ...

        execute_action.return_value = returned({"status": 204})
        assert (await maybe()).status_code == 204

        execute_action.return_value = returned(None)
        assert await maybe() is None


class TestHttpResponseOutputSchema:
    async def test_a_response_return_type_sends_the_mock_http_response_schema(
        self, in_eval_trial, execute_action, returned
    ):
        execute_action.return_value = returned({"status": 200})

        await get_page("https://erp.invalid")

        (call,) = sent(execute_action)
        assert call["output_schema"] == MockHttpResponse.model_json_schema()
        assert "status" in call["output_schema"]["properties"]

    async def test_an_optional_response_allows_null_in_the_schema(self, in_eval_trial, execute_action, returned):
        @mockable("erp.maybe")
        async def maybe() -> Optional[httpx.Response]: ...

        execute_action.return_value = returned(None)

        await maybe()

        (call,) = sent(execute_action)
        assert call["output_schema"] == TypeAdapter(MockHttpResponse | None).json_schema()
        assert {"type": "null"} in call["output_schema"]["anyOf"]


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

    async def test_a_type_that_is_not_an_exception_class_raises_the_lookup_error_without_running_it(
        self, in_eval_trial, execute_action, raised
    ):
        execute_action.return_value = raised("os.system", "touch /tmp/pwned")

        with pytest.raises(mocks.MockFailedError, match="^os.system is not an exception class"):
            await fetch_order("O1")

    async def test_a_module_getattr_is_not_called_for_the_type(
        self, in_eval_trial, execute_action, raised, monkeypatch
    ):
        lazy_module = types.ModuleType("lazy_errors")
        lazy_module.__getattr__ = Mock(side_effect=AttributeError)
        monkeypatch.setitem(sys.modules, "lazy_errors", lazy_module)
        execute_action.return_value = raised("lazy_errors.LazyError", "boom")

        with pytest.raises(mocks.MockFailedError, match="^lazy_errors.LazyError is not an exception class"):
            await fetch_order("O1")

        lazy_module.__getattr__.assert_not_called()

    async def test_an_exception_defined_in_code_run_by_exec_is_read_from_its_globals(
        self, in_eval_trial, execute_action, raised
    ):
        cancel_order = _exec_skill_code()["cancel_order"]
        execute_action.return_value = raised("skill_code_run_by_exec.OrderLockedError", "locked")

        with pytest.raises(Exception, match="^locked$") as error:
            await cancel_order("O1")

        assert type(error.value).__name__ == "OrderLockedError"

    async def test_a_name_in_its_globals_that_is_not_an_exception_class_raises_the_lookup_error(
        self, in_eval_trial, execute_action, raised
    ):
        cancel_order = _exec_skill_code()["cancel_order"]
        execute_action.return_value = raised("skill_code_run_by_exec.cancel_order", "boom")

        with pytest.raises(mocks.MockFailedError, match="^skill_code_run_by_exec.cancel_order is not an exception"):
            await cancel_order("O1")

    async def test_an_httpx_transport_error(self, in_eval_trial, execute_action, raised):
        execute_action.return_value = raised("httpx.ConnectTimeout", "timed out")

        with pytest.raises(httpx.ConnectTimeout, match="timed out"):
            await get_page("https://erp.invalid")

    async def test_a_mock_failure_raises_mock_failed_error_with_the_engine_message(
        self, in_eval_trial, execute_action, mock_failed
    ):
        execute_action.return_value = mock_failed("erp.order:O1#3: the mock list for this call ran out")

        with pytest.raises(mocks.MockFailedError, match="^erp.order:O1#3: the mock list for this call ran out$"):
            await fetch_order("O1")

    def test_a_sync_mock_failure_raises_mock_failed_error(self, in_eval_trial, execute_action, mock_failed):
        execute_action.return_value = mock_failed("erp.status#1: no mock")

        with pytest.raises(mocks.MockFailedError, match="^erp.status#1: no mock$"):
            fetch_status_sync()

    async def test_a_failed_request_propagates(self, in_eval_trial, execute_action):
        execute_action.side_effect = RuntimeError("Action mock_call FAILED")

        with pytest.raises(RuntimeError, match="mock_call"):
            await fetch_order("O1")


class TestRequest:
    async def test_async_sends_the_call(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        await fetch_order("O1")

        action, call = execute_action.call_args.args
        assert action == "mock_call"
        assert execute_action.call_args.kwargs == {}
        assert call == {
            "name": "erp.order",
            "input": {"order_id": "O1", "realm": "prod"},
            "output_schema": Order.model_json_schema(),
            "call_id": call["call_id"],
        }

    def test_sync_sends_arguments_by_name(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        fetch_order_sync(realm="test", order_id="O1")

        (call,) = sent(execute_action)
        assert call["input"] == {"order_id": "O1", "realm": "test"}

    def test_secret_arguments_are_never_sent(self, in_eval_trial, execute_action, returned):
        @mockable("erp.token")
        def fetch_token(url: str, headers: dict, auth: str, token: str, credentials: dict): ...

        execute_action.return_value = returned(None)
        fetch_token("https://erp.invalid", {"Authorization": "Bearer x"}, "basic", "t0k", {"id": "c1"})

        assert sent(execute_action)[0]["input"] == {"url": "https://erp.invalid"}

    def test_secret_arguments_passed_through_kwargs_are_never_sent(self, in_eval_trial, execute_action, returned):
        @mockable("erp.request")
        def request(method: str, url: str, **kwargs): ...

        execute_action.return_value = returned(None)
        request("GET", "https://erp.invalid", headers={"Authorization": "Bearer x"}, token="t0k", timeout=5)

        assert sent(execute_action)[0]["input"] == {"method": "GET", "url": "https://erp.invalid", "timeout": 5}

    def test_arguments_named_like_a_credential_are_never_sent(self, in_eval_trial, execute_action, returned):
        @mockable("erp.login")
        def login(url: str, api_key: str, Password: str, client_secret: str, **kwargs): ...

        execute_action.return_value = returned(None)
        login("https://erp.invalid", "k1", "p1", "cs1", Authorization="Bearer x", refresh_token="t0k", page=2)

        assert sent(execute_action)[0]["input"] == {"url": "https://erp.invalid", "page": 2}

    def test_only_whole_credential_names_are_left_out(self, in_eval_trial, execute_action, returned):
        @mockable("llm.complete")
        def complete(**kwargs): ...

        kept = [
            "max_tokens",
            "keys",
            "key",
            "sort_key",
            "keyword",
            "secretary",
            "authorization_id",
            "extra_headers",
        ]
        dropped = [
            "access_token",
            "x_api_key",
            "db_password",
            "client_credentials",
            "Secret",
            "aws_secret_access_key",
            "private_key",
            "passphrase",
            "passwd",
            "pwd",
            "cookie",
            "session_cookie",
            "jwt",
        ]
        execute_action.return_value = returned(None)
        complete(**{name: 1 for name in kept + dropped})

        assert sent(execute_action)[0]["input"] == {name: 1 for name in kept}

    def test_credential_keys_inside_a_dict_argument_are_never_sent(self, in_eval_trial, execute_action, returned):
        @mockable("erp.send")
        def send(config: dict, requests: list): ...

        execute_action.return_value = returned(None)
        send(
            {"region": "eu", "api_key": "k1", "nested": {"Authorization": "Bearer x", "page": 2}},
            [{"headers": {"cookie": "c"}, "path": "/orders"}],
        )

        assert sent(execute_action)[0]["input"] == {
            "config": {"region": "eu", "nested": {"page": 2}},
            "requests": [{"path": "/orders"}],
        }

    async def test_a_method_never_sends_its_instance(self, in_eval_trial, execute_action, returned):
        class Client:
            def __init__(self, token: str):
                self.token = token

            @mockable("erp.order")
            async def fetch(self, order_id: str) -> dict:
                return {}

            @classmethod
            @mockable("erp.status")
            def status(cls, realm: str) -> str:
                return "live"

        execute_action.return_value = returned({})
        await Client("t0k").fetch("O1")
        execute_action.return_value = returned("live")
        Client.status("prod")

        assert [call["input"] for call in sent(execute_action)] == [{"order_id": "O1"}, {"realm": "prod"}]

    def test_an_argument_json_cannot_hold_is_sent_as_its_repr(self, in_eval_trial, execute_action, returned):
        class Session:
            def __repr__(self):
                return "<Session>"

        @mockable("erp.post")
        def post(session: Session, order: Order): ...

        execute_action.return_value = returned(None)
        post(Session(), Order(id="O1", total=7))

        assert sent(execute_action)[0]["input"] == {"session": "<Session>", "order": {"id": "O1", "total": 7}}

    def test_an_argument_that_contains_itself_is_sent_as_its_type_only(self, in_eval_trial, execute_action, returned):
        @mockable("erp.post")
        def post(lines: list, page: int): ...

        lines: list = []
        lines.append(lines)
        execute_action.return_value = returned(None)
        post(lines, 2)

        assert sent(execute_action)[0]["input"] == {"lines": "<list that contains itself>", "page": 2}

    def test_an_argument_that_contains_itself_does_not_send_its_credentials(
        self, in_eval_trial, execute_action, returned
    ):
        @mockable("erp.connect")
        def connect(config: dict): ...

        config: dict = {"host": "erp", "password": "secret"}
        config["self"] = config
        execute_action.return_value = returned(None)
        connect(config)

        assert sent(execute_action)[0]["input"] == {"config": "<dict that contains itself>"}

    def test_bytes_are_sent_as_base64(self, in_eval_trial, execute_action, returned):
        @mockable("erp.upload")
        def upload(name: bytes, content: bytes): ...

        execute_action.return_value = returned(None)
        upload(b"invoice.pdf", b"%PDF\xff")

        assert sent(execute_action)[0]["input"] == {"name": "aW52b2ljZS5wZGY=", "content": "JVBERv8="}

    def test_every_call_has_its_own_call_id(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned("down")

        fetch_status_sync()
        fetch_status_sync()

        first, second = (call["call_id"] for call in sent(execute_action))
        assert first != second


class TestOnTheExecutor:
    async def test_async_reads_the_bound_id_through_the_action_response(
        self, in_eval_trial_on_actions_hub, execute_action, returned, action_response
    ):
        execute_action.return_value = action_response(returned({"id": "O1", "total": 7}))

        assert await fetch_order("O1") == Order(id="O1", total=7)
        assert sent(execute_action)[0]["call_id"] == "workflow-uuid"

    async def test_a_mock_failure_raises_mock_failed_error(
        self, in_eval_trial_on_actions_hub, execute_action, mock_failed, action_response
    ):
        execute_action.return_value = action_response(mock_failed("erp.order:O1#1: no mock"))

        with pytest.raises(mocks.MockFailedError, match="^erp.order:O1#1: no mock$"):
            await fetch_order("O1")

    async def test_a_string_return_annotation_is_not_evaluated(
        self, in_eval_trial_on_actions_hub, execute_action, returned, action_response
    ):
        @mockable("erp.order")
        async def fetch() -> "Order":
            raise NotImplementedError

        execute_action.return_value = action_response(returned({"id": "O1", "total": 7}))

        assert await fetch() == {"id": "O1", "total": 7}

    async def test_a_string_nested_in_the_return_annotation_is_not_evaluated(
        self, in_eval_trial_on_actions_hub, execute_action, returned, action_response
    ):
        @mockable("erp.orders")
        async def fetch() -> list["Order"]:
            raise NotImplementedError

        execute_action.return_value = action_response(returned([{"id": "O1", "total": 7}]))

        assert await fetch() == [{"id": "O1", "total": 7}]

    async def test_a_literal_return_annotation_is_still_validated(
        self, in_eval_trial_on_actions_hub, execute_action, returned, action_response
    ):
        @mockable("erp.state")
        async def fetch() -> Optional[Literal["open", "closed"]]:
            raise NotImplementedError

        execute_action.return_value = action_response(returned("pending"))

        with pytest.raises(ValidationError):
            await fetch()

    async def test_a_failed_action_raises(self, in_eval_trial_on_actions_hub, execute_action, action_response):
        execute_action.return_value = action_response(status="FAILED", error="no eval trial")

        with pytest.raises(RuntimeError, match="^mock_call action-1 FAILED: no eval trial$"):
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

        assert drained_steps() == []
        assert [call.kwargs["action_name"] for call in run.call_args_list] == ["mock_call"]

    async def test_an_ordinary_action_in_the_same_setup_is_logged(self, in_eval_trial):
        configure_auto_action_logs(True)
        start_log_capture()
        with patch.object(ActionExecutor, "_execute_action", new_callable=AsyncMock) as run:
            run.return_value = {"ok": True}
            await ActionExecutor.execute("do_thing", {"a": 1})

        assert [entry["event"] for entry in drained_steps()] == ["action"]
        assert "emit_log" in [call.kwargs["action_name"] for call in run.call_args_list]
