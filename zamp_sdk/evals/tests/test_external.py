import sys
import types

import pytest
from pydantic import BaseModel

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


class TestOutsideAnEvalRun:
    async def test_async_runs_untouched(self, door):
        assert await fetch_order("O1") == Order(id="O1", total=-1)
        door.assert_not_called()

    def test_sync_runs_untouched(self, door):
        assert fetch_order_sync("O1") == Order(id="O1", total=-1)
        door.assert_not_called()

    def test_keeps_the_function_name(self):
        assert fetch_order.__name__ == "fetch_order"
        assert fetch_order_sync.__name__ == "fetch_order_sync"


class TestReturns:
    async def test_async_returns_the_fixture_as_the_return_type(self, eval_run, door, reply):
        door.return_value = reply(key="O1", returns={"id": "O1", "total": 7})

        assert await fetch_order("O1") == Order(id="O1", total=7)

    def test_sync_returns_the_fixture_as_the_return_type(self, eval_run, door, reply):
        door.return_value = reply(key="O1", returns={"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_sync_call_inside_a_running_loop(self, eval_run, door, reply):
        door.return_value = reply(key="O1", returns={"id": "O1", "total": 7})

        assert fetch_order_sync("O1") == Order(id="O1", total=7)

    async def test_without_an_annotation_returns_the_raw_value(self, eval_run, door, reply):
        door.return_value = reply(name="erp.status", returns={"state": "down"})

        assert await fetch_status() == {"state": "down"}

    async def test_a_human_ask_returns_none(self, eval_run, door, reply):
        @evals.external("ask.decision")
        async def ask() -> None: ...

        door.return_value = reply(name="ask.decision", returns=None)

        assert await ask() is None

    async def test_an_http_response_is_built_from_status_body_and_headers(self, eval_run, door, reply, monkeypatch):
        class Response:
            def __init__(self, status_code, headers=None, json=None, text=None):
                self.status_code, self.headers, self.json, self.text = status_code, headers, json, text

        monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(Response=Response))

        @evals.external("erp.page")
        async def get_page(url: str) -> Response:
            return Response(200)

        door.return_value = reply(
            name="erp.page", returns={"status": 503, "body": {"error": "busy"}, "headers": {"A": "b"}}
        )
        response = await get_page("https://erp.invalid")

        assert (response.status_code, response.json, response.headers) == (503, {"error": "busy"}, {"A": "b"})

        door.return_value = reply(name="erp.page", returns={"status": 200, "body": "<html/>"})
        response = await get_page("https://erp.invalid")

        assert (response.status_code, response.text, response.json) == (200, "<html/>", None)


class TestRaises:
    async def test_async_raises_the_fixture_error(self, eval_run, door, reply):
        door.return_value = reply(key="O1", raises={"type": "builtins.TimeoutError", "message": "read timed out"})

        with pytest.raises(TimeoutError, match="read timed out"):
            await fetch_order("O1")

    def test_sync_raises_the_fixture_error(self, eval_run, door, reply):
        door.return_value = reply(key="O1", raises={"type": "builtins.ConnectionError", "message": "refused"})

        with pytest.raises(ConnectionError, match="refused"):
            fetch_order_sync("O1")

    def test_an_sdk_error_type_is_importable(self, eval_run, door, reply):
        door.return_value = reply(key="O1", raises={"type": "zamp_sdk.AgentDbError", "message": "boom"})

        with pytest.raises(AgentDbError, match="boom"):
            fetch_order_sync("O1")

    async def test_a_fixture_error_fails_the_call_naming_the_call_id(self, eval_run, door, reply):
        door.return_value = reply(key="O1", n=3, fixture_error="FIXTURE_EXHAUSTED")

        with pytest.raises(LookupError, match="erp.order:O1#3: FIXTURE_EXHAUSTED"):
            await fetch_order("O1")

    async def test_a_failed_door_call_propagates(self, eval_run, door):
        door.side_effect = RuntimeError("Action eval_door FAILED")

        with pytest.raises(RuntimeError, match="eval_door"):
            await fetch_order("O1")


class TestDoorCall:
    async def test_async_sends_name_key_args_and_caller(self, eval_run, door, reply):
        door.return_value = reply(key="O1", returns={"id": "O1", "total": 7})

        await fetch_order("O1")

        action, params = door.call_args.args
        assert action == "eval_door"
        assert params["kind"] == "external"
        assert (params["name"], params["key"]) == ("erp.order", "O1")
        assert params["args"] == {"order_id": "O1", "realm": "prod"}
        assert params["parent"].endswith("test_external.py:test_async_sends_name_key_args_and_caller")
        assert params["returns"] is None and params["raises"] is None

    def test_sync_sends_the_caller_as_parent(self, eval_run, door, reply):
        door.return_value = reply(key="O1", returns={"id": "O1", "total": 7})

        fetch_order_sync(realm="test", order_id="O1")

        params = door.call_args.args[1]
        assert params["args"] == {"order_id": "O1", "realm": "test"}
        assert params["parent"].endswith("test_external.py:test_sync_sends_the_caller_as_parent")

    def test_no_key_sends_none(self, eval_run, door, reply):
        door.return_value = reply(name="erp.status", returns="down")

        assert fetch_status_sync() == "down"
        assert door.call_args.args[1]["key"] is None

    def test_a_non_string_key_is_sent_as_text(self, eval_run, door, reply):
        @evals.external("erp.page", key="page")
        def get_page(page: int): ...

        door.return_value = reply(name="erp.page", key="2", returns=None)
        get_page(2)

        assert door.call_args.args[1]["key"] == "2"

    def test_every_call_has_its_own_call_id(self, eval_run, door, reply):
        door.return_value = reply(name="erp.status", returns="down")

        fetch_status_sync()
        fetch_status_sync()

        first, second = (call.args[1]["call_id"] for call in door.call_args_list)
        assert first != second
