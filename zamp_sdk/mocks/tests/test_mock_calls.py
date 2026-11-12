import ast
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from zamp_sdk import ActionExecutor, mocks
from zamp_sdk.decorated_calls.utils import arguments_without_credentials
from zamp_sdk.mocks import mockable
from zamp_sdk.mocks.models import MockCall, MockDecision


class Order(BaseModel):
    id: str
    total: int


real_calls: list[str] = []


@mockable("erp.order")
async def fetch_order(order_id: str, api_key: str = "k1") -> Order:
    real_calls.append(order_id)
    return Order(id=order_id, total=-1)


@mockable("erp.order")
def fetch_order_sync(order_id: str, api_key: str = "k1") -> Order:
    real_calls.append(order_id)
    return Order(id=order_id, total=-1)


@pytest.fixture(autouse=True)
def _no_real_calls_yet():
    real_calls.clear()


def sent(execute_action):
    return [call.args[1] for call in execute_action.call_args_list]


class TestGate:
    async def test_no_case_runs_function_without_asking(self, execute_action):
        assert await fetch_order("O1") == Order(id="O1", total=-1)
        assert fetch_order_sync("O2") == Order(id="O2", total=-1)

        execute_action.assert_not_called()
        assert real_calls == ["O1", "O2"]

    async def test_an_eval_trial_without_a_case_runs_function_without_asking(self, in_eval_trial, execute_action):
        assert await fetch_order("O1") == Order(id="O1", total=-1)

        execute_action.assert_not_called()

    async def test_case_sends_mock_call_with_case_id_and_journal_free_input(
        self, in_mock_case, execute_action, run_real
    ):
        execute_action.return_value = run_real

        await fetch_order("O1", api_key="secret-k")

        action, call = execute_action.call_args.args
        assert action == "mock_call"
        assert call == {
            "case_id": "case-1",
            "name": "erp.order",
            "input": {"order_id": "O1"},
            "output_schema": Order.model_json_schema(),
            "call_id": call["call_id"],
        }
        assert call["call_id"]

    async def test_case_id_from_actions_hub_context(
        self, in_mock_case_on_actions_hub, execute_action, run_real, action_response
    ):
        execute_action.return_value = action_response(run_real)

        await fetch_order("O1")

        assert sent(execute_action)[0]["case_id"] == "case-1"


class TestDecision:
    async def test_run_real_runs_function(self, in_mock_case, execute_action, run_real):
        execute_action.return_value = run_real

        assert await fetch_order("O1") == Order(id="O1", total=-1)
        assert fetch_order_sync("O2") == Order(id="O2", total=-1)
        assert real_calls == ["O1", "O2"]

    async def test_answered_returned_is_returned(self, in_mock_case, execute_action, answered_returned):
        execute_action.return_value = answered_returned({"id": "O1", "total": 7})

        assert await fetch_order("O1") == Order(id="O1", total=7)
        assert fetch_order_sync("O1") == Order(id="O1", total=7)
        assert real_calls == []

    async def test_answered_raised_is_raised(self, in_mock_case, execute_action, answered_raised):
        execute_action.return_value = answered_raised("builtins.TimeoutError", "read timed out")

        with pytest.raises(TimeoutError, match="^read timed out$"):
            await fetch_order("O1")
        assert real_calls == []

    async def test_mock_failed_is_mock_failed_error(self, in_mock_case, execute_action, answered_mock_failed):
        execute_action.return_value = answered_mock_failed("The request could not be completed.")

        with pytest.raises(mocks.MockFailedError, match="^The request could not be completed.$"):
            await fetch_order("O1")
        with pytest.raises(mocks.MockFailedError, match="^The request could not be completed.$"):
            fetch_order_sync("O1")
        assert real_calls == []

    @pytest.mark.parametrize(
        "reply",
        [
            {"kind": "returned", "value": {"id": "O1", "total": 7}},
            {"decision": "answered", "outcome": {"kind": "mock_failed", "code": "MOCK_FAILED", "message": "m"}},
            {"decision": "skipped"},
            None,
        ],
    )
    async def test_unknown_reply_is_mock_failed_error(self, in_mock_case, execute_action, reply):
        execute_action.return_value = reply

        with pytest.raises(mocks.MockFailedError, match="^erp.order: mocks replied with something that is not a"):
            await fetch_order("O1")
        assert real_calls == []

    async def test_a_rejected_reply_is_raised_without_its_cause_chain(self, in_mock_case, execute_action):
        execute_action.return_value = {"decision": "answered", "outcome": {"kind": "returned", "secret": "s3cr3t"}}

        with pytest.raises(mocks.MockFailedError) as raised:
            await fetch_order("O1")

        printed = "".join(traceback.format_exception(raised.value))
        assert raised.value.__cause__ is None
        assert "ValidationError" not in printed
        assert "s3cr3t" not in printed


class TestReplyModels:
    def test_reply_models_live_in_mocks(self):
        decisions = TypeAdapter(MockDecision)
        wire = [
            {"decision": "run_real"},
            {"decision": "answered", "outcome": {"kind": "returned", "value": None}},
            {"decision": "answered", "outcome": {"kind": "raised", "type": "builtins.ValueError", "message": "m"}},
            {"decision": "answered", "outcome": {"kind": "mock_failed", "message": "m"}},
        ]

        assert [decisions.dump_python(decisions.validate_python(reply), mode="json") for reply in wire] == wire
        with pytest.raises(ValidationError):
            decisions.validate_python({"decision": "run_real", "extra": 1})
        assert set(MockCall.model_fields) == {"case_id", "name", "input", "output_schema", "call_id"}


class TestTheAskCarriesNoCase:
    async def test_mock_call_request_has_no_case_header_while_the_real_call_does(self, in_mock_case, monkeypatch):
        monkeypatch.setenv("ZAMP_BASE_URL", "https://api.zamp.test")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "tok")
        results = iter([{"decision": "run_real"}, {"id": "O1", "total": 7}])
        headers_by_action = []

        def client(base_url, default_headers):
            def post(endpoint, data):
                headers_by_action.append((data["action_name"], default_headers.get("X-MOCK-CASE-ID")))
                return {"id": "action-1"}

            http = AsyncMock()
            http.post.side_effect = post
            http.get.return_value = {"status": "COMPLETED", "result": next(results)}
            return http

        @mockable("erp.order")
        async def fetch_real_order(order_id: str) -> Order:
            return Order.model_validate(await ActionExecutor.execute("erp_fetch_order", {"order_id": order_id}))

        with patch("zamp_sdk.action_executor.action_executor.HttpClient", side_effect=client):
            assert await fetch_real_order("O1") == Order(id="O1", total=7)

        assert headers_by_action == [("mock_call", None), ("erp_fetch_order", "case-1")]


class TestOnTheActionsHub:
    async def test_the_ask_goes_through_the_action_gateway_never_actions_hub(
        self, in_mock_case_on_actions_hub, monkeypatch
    ):
        actions_hub = SimpleNamespace(ActionsHub=SimpleNamespace(ask_mocks=AsyncMock(), execute_action=AsyncMock()))
        monkeypatch.setitem(sys.modules, "zamp_public_workflow_sdk", SimpleNamespace(actions_hub=actions_hub))
        monkeypatch.setitem(sys.modules, "zamp_public_workflow_sdk.actions_hub", actions_hub)
        gateway = AsyncMock(
            return_value={
                "id": "action-1",
                "status": "COMPLETED",
                "result": {"decision": "answered", "outcome": {"kind": "returned", "value": {"id": "O1", "total": 7}}},
                "error": None,
            }
        )
        with (
            patch("zamp_sdk.action_executor.routing.get_action_gateway", return_value=gateway),
            patch("zamp_sdk.action_executor.routing.is_registered_locally", new=AsyncMock(return_value=False)),
        ):
            assert await fetch_order("O1", api_key="secret-k") == Order(id="O1", total=7)

        action_name, params = gateway.call_args.args
        assert action_name == "mock_call"
        assert params == {
            "case_id": "case-1",
            "name": "erp.order",
            "input": {"order_id": "O1"},
            "output_schema": Order.model_json_schema(),
            "call_id": "workflow-uuid",
        }
        actions_hub.ActionsHub.ask_mocks.assert_not_called()
        actions_hub.ActionsHub.execute_action.assert_not_called()


class TestLayering:
    def test_mocks_does_not_depend_on_evals(self):
        mocks_package = Path(mocks.__file__).parent
        imported = {
            node.module
            for path in mocks_package.rglob("*.py")
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.ImportFrom) and node.module
        }

        assert {module for module in imported if module.startswith("zamp_sdk.evals")} == set()


class TestCredentialNamesAreStrippedInAnyCasing:
    @pytest.mark.parametrize(
        "name", ["accessToken", "clientSecret", "authToken", "privateKey", "Api-Key", "DB_PASSWORD"]
    )
    def test_a_credential_name_is_not_sent(self, name):
        sent = arguments_without_credentials({name: "CANARY", "orderId": "O1"})

        assert sent == {"orderId": "O1"}
