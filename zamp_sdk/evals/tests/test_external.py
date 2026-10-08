import asyncio
import base64
import inspect
from typing import Optional

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from zamp_sdk import AgentDbError, evals


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


def sent(door):
    return [call.args[1] for call in door.call_args_list]


class TestOutsideAnEvalRun:
    async def test_async_runs_untouched(self, door):
        assert await fetch_order("O1") == Order(id="O1", total=-1)

        door.assert_not_called()

    def test_sync_runs_untouched(self, door):
        assert fetch_order_sync("O1") == Order(id="O1", total=-1)

        door.assert_not_called()

    def test_keeps_the_function_name_and_kind(self):
        assert fetch_order.__name__ == "fetch_order"
        assert fetch_order_sync.__name__ == "fetch_order_sync"
        assert inspect.iscoroutinefunction(fetch_order)
        assert not inspect.iscoroutinefunction(fetch_order_sync)


class TestReturns:
    async def test_async_returns_the_fixture_as_the_return_type(self, eval_run, door, reply):
        door.return_value = reply(returns={"id": "O1", "total": 7})

        assert await fetch_order("O1") == Order(id="O1", total=7)

    def test_sync_returns_the_fixture_as_the_return_type(self, eval_run, door, reply):
        door.return_value = reply(returns={"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_sync_call_inside_a_running_loop(self, eval_run, door, reply):
        door.return_value = reply(returns={"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_without_an_annotation_returns_the_raw_value(self, eval_run, door, reply):
        door.return_value = reply(returns={"state": "down"})

        assert await fetch_status() == {"state": "down"}

    async def test_a_human_ask_returns_none(self, eval_run, door, reply):
        @evals.external("ask.decision")
        async def ask() -> None: ...

        door.return_value = reply(returns=None)

        assert await ask() is None

    async def test_a_reply_without_an_outcome_is_rejected(self, eval_run, door, reply):
        door.return_value = reply()

        with pytest.raises(ValidationError, match="exactly one of returns, raises or fixture_error"):
            await fetch_order("O1")

    async def test_a_reply_with_two_outcomes_is_rejected(self, eval_run, door, reply):
        door.return_value = reply(returns={"id": "O1", "total": 7}, fixture_error="FIXTURE_MISSING")

        with pytest.raises(ValidationError, match="exactly one of returns, raises or fixture_error"):
            await fetch_order("O1")


class TestHttpResponse:
    async def test_built_from_status_json_body_and_headers(self, eval_run, door, reply):
        door.return_value = reply(returns={"status": 200, "body": {"id": "O1"}, "headers": {"X-Page": "1"}})

        response = await get_page("https://erp.invalid")

        assert (response.status_code, response.json(), response.headers["X-Page"]) == (200, {"id": "O1"}, "1")

    async def test_a_string_body_is_text(self, eval_run, door, reply):
        door.return_value = reply(returns={"status": 200, "body": "<html/>"})

        assert (await get_page("https://erp.invalid")).text == "<html/>"

    async def test_content_is_the_decoded_bytes(self, eval_run, door, reply):
        door.return_value = reply(returns={"status": 200, "content": base64.b64encode(b"%PDF-1.7").decode()})

        assert (await get_page("https://erp.invalid")).content == b"%PDF-1.7"

    async def test_an_http_error_raises_on_raise_for_status(self, eval_run, door, reply):
        door.return_value = reply(returns={"status": 503, "body": {"error": "busy"}})

        response = await get_page("https://erp.invalid")

        with pytest.raises(httpx.HTTPStatusError, match="503"):
            response.raise_for_status()

    async def test_an_optional_response(self, eval_run, door, reply):
        @evals.external("erp.maybe")
        async def maybe() -> Optional[httpx.Response]: ...

        door.return_value = reply(returns={"status": 204})
        assert (await maybe()).status_code == 204

        door.return_value = reply(returns=None)
        assert await maybe() is None

    async def test_a_plain_response_never_comes_back_as_none(self, eval_run, door, reply):
        door.return_value = reply(returns=None)

        with pytest.raises(ValidationError):
            await get_page("https://erp.invalid")

    async def test_body_and_content_together_are_rejected(self, eval_run, door, reply):
        content = base64.b64encode(b"%PDF-1.7").decode()
        door.return_value = reply(returns={"status": 200, "body": "<html/>", "content": content})

        with pytest.raises(ValidationError, match="a body or content, not both"):
            await get_page("https://erp.invalid")


class TestRaises:
    async def test_async_raises_the_fixture_error(self, eval_run, door, reply):
        door.return_value = reply(raises={"type": "builtins.TimeoutError", "message": "read timed out"})

        with pytest.raises(TimeoutError, match="read timed out"):
            await fetch_order("O1")

    def test_sync_raises_the_fixture_error(self, eval_run, door, reply):
        door.return_value = reply(raises={"type": "builtins.ConnectionError", "message": "refused"})

        with pytest.raises(ConnectionError, match="refused"):
            fetch_order_sync("O1")

    def test_an_sdk_error_type_is_importable(self, eval_run, door, reply):
        door.return_value = reply(raises={"type": "zamp_sdk.AgentDbError", "message": "boom"})

        with pytest.raises(AgentDbError, match="boom"):
            fetch_order_sync("O1")

    async def test_an_httpx_transport_error(self, eval_run, door, reply):
        door.return_value = reply(raises={"type": "httpx.ConnectTimeout", "message": "timed out"})

        with pytest.raises(httpx.ConnectTimeout, match="timed out"):
            await get_page("https://erp.invalid")

    async def test_a_fixture_error_raises_fixture_error_naming_the_call_id(self, eval_run, door, reply):
        door.return_value = reply(n=3, fixture_error="FIXTURE_EXHAUSTED")

        with pytest.raises(evals.FixtureError, match="^erp.order:O1#3: FIXTURE_EXHAUSTED$"):
            await fetch_order("O1")

    def test_a_missing_fixture_without_a_key(self, eval_run, door, reply):
        door.return_value = reply(fixture_error="FIXTURE_MISSING")

        with pytest.raises(evals.FixtureError, match="^erp.status#1: FIXTURE_MISSING$"):
            fetch_status_sync()

    async def test_a_failed_door_call_propagates(self, eval_run, door):
        door.side_effect = RuntimeError("Action eval_door FAILED")

        with pytest.raises(RuntimeError, match="eval_door"):
            await fetch_order("O1")


class TestDoorCall:
    async def test_async_sends_the_call(self, eval_run, door, reply):
        door.return_value = reply(returns={"id": "O1", "total": 7})

        await fetch_order("O1")

        action, call = door.call_args.args
        assert action == "eval_door"
        assert door.call_args.kwargs == {"log_action": False}
        assert call == {
            "kind": "external",
            "call_id": call["call_id"],
            "name": "erp.order",
            "key": "O1",
            "parent": "test_external.py:test_async_sends_the_call",
            "args": {"order_id": "O1", "realm": "prod"},
            "returns": None,
            "raises": None,
        }

    def test_sync_sends_arguments_by_name(self, eval_run, door, reply):
        door.return_value = reply(returns={"id": "O1", "total": 7})

        fetch_order_sync(realm="test", order_id="O1")

        (call,) = sent(door)
        assert call["args"] == {"order_id": "O1", "realm": "test"}
        assert call["parent"] == "test_external.py:test_sync_sends_arguments_by_name"

    async def test_parallel_calls_name_their_caller(self, eval_run, door, reply):
        door.return_value = reply(returns={"id": "O1", "total": 7})

        await asyncio.gather(fetch_order("O1"), fetch_order("O2"))

        assert {call["parent"] for call in sent(door)} == {"test_external.py:test_parallel_calls_name_their_caller"}

    def test_no_key_sends_none(self, eval_run, door, reply):
        door.return_value = reply(returns="down")

        fetch_status_sync()

        assert sent(door)[0]["key"] is None

    def test_a_none_key_value_sends_none(self, eval_run, door, reply):
        @evals.external("erp.page", key="page")
        def get_page_number(page: int | None): ...

        door.return_value = reply(returns=None)
        get_page_number(None)

        assert sent(door)[0]["key"] is None

    def test_a_non_string_key_is_sent_as_text(self, eval_run, door, reply):
        @evals.external("erp.page", key="page")
        def get_page_number(page: int): ...

        door.return_value = reply(returns=None)
        get_page_number(2)

        assert sent(door)[0]["key"] == "2"

    def test_secret_arguments_are_never_sent(self, eval_run, door, reply):
        @evals.external("erp.token")
        def fetch_token(url: str, headers: dict, auth: str, token: str, credentials: dict): ...

        door.return_value = reply(returns=None)
        fetch_token("https://erp.invalid", {"Authorization": "Bearer x"}, "basic", "t0k", {"id": "c1"})

        assert sent(door)[0]["args"] == {"url": "https://erp.invalid"}

    async def test_a_method_never_sends_its_instance(self, eval_run, door, reply):
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

        door.return_value = reply(returns={})
        await Client("t0k").fetch("O1")
        door.return_value = reply(returns="live")
        Client.status("prod")

        assert [call["args"] for call in sent(door)] == [{"order_id": "O1"}, {"realm": "prod"}]

    def test_an_argument_json_cannot_hold_is_sent_as_its_repr(self, eval_run, door, reply):
        class Session:
            def __repr__(self):
                return "<Session>"

        @evals.external("erp.post")
        def post(session: Session, order: Order): ...

        door.return_value = reply(returns=None)
        post(Session(), Order(id="O1", total=7))

        assert sent(door)[0]["args"] == {"session": "<Session>", "order": {"id": "O1", "total": 7}}

    def test_every_call_has_its_own_call_id(self, eval_run, door, reply):
        door.return_value = reply(returns="down")

        fetch_status_sync()
        fetch_status_sync()

        first, second = (call["call_id"] for call in sent(door))
        assert first != second


class TestDecoration:
    def test_a_key_that_is_not_a_parameter_fails_at_decoration(self):
        with pytest.raises(ValueError, match="erp.order: key 'id' is not a parameter of .*fetch"):

            @evals.external("erp.order", key="id")
            def fetch(order_id: str): ...

    @pytest.mark.parametrize("name", ["erp", "erp order.get", "ERP.order", "erp.order#1"])
    def test_a_bad_name_fails_at_decoration(self, name):
        with pytest.raises(ValueError, match="is not a call name"):

            @evals.external(name)
            def fetch(): ...

    @pytest.mark.parametrize("order_id", ["O 1", "O#1", ""])
    async def test_a_key_value_that_cannot_be_a_trace_key_fails_before_the_door(self, eval_run, door, order_id):
        with pytest.raises(ValueError, match=f"erp.order: key 'order_id' is '{order_id}'; a key value has no spaces"):
            await fetch_order(order_id)

        door.assert_not_called()


class TestOnTheExecutor:
    async def test_async_reads_the_bound_id_and_unwraps_the_gateway_envelope(
        self, executor_eval_run, gateway, reply, envelope
    ):
        gateway.return_value = envelope(reply(returns={"id": "O1", "total": 7}))

        assert await fetch_order("O1") == Order(id="O1", total=7)
        assert sent(gateway)[0]["call_id"] == "workflow-uuid"

    async def test_a_fixture_error_comes_through_the_envelope(self, executor_eval_run, gateway, reply, envelope):
        gateway.return_value = envelope(reply(fixture_error="FIXTURE_MISSING"))

        with pytest.raises(evals.FixtureError, match="^erp.order:O1#1: FIXTURE_MISSING$"):
            await fetch_order("O1")

    async def test_a_failed_door_action_raises(self, executor_eval_run, gateway, envelope):
        gateway.return_value = envelope(status="FAILED", error="no eval run")

        with pytest.raises(RuntimeError, match="^Action action-1 FAILED: no eval run$"):
            await fetch_order("O1")

    def test_sync_refuses_in_workflow_code(self, executor_eval_run, gateway):
        with pytest.raises(RuntimeError, match="erp.order: a sync function cannot reach the eval door"):
            fetch_order_sync("O1")

        gateway.assert_not_called()
