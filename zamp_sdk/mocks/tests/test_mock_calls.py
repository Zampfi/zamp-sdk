import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from zamp_sdk import mocks
from zamp_sdk.mocks import mockable


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

    async def test_case_id_from_env_or_context(
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

    async def test_answered_returned_is_returned(self, in_mock_case, execute_action, returned):
        execute_action.return_value = returned({"id": "O1", "total": 7})

        assert await fetch_order("O1") == Order(id="O1", total=7)
        assert fetch_order_sync("O1") == Order(id="O1", total=7)
        assert real_calls == []

    async def test_answered_raised_is_raised(self, in_mock_case, execute_action, raised):
        execute_action.return_value = raised("builtins.TimeoutError", "read timed out")

        with pytest.raises(TimeoutError, match="^read timed out$"):
            await fetch_order("O1")
        assert real_calls == []

    async def test_mock_failed_is_mock_failed_error(self, in_mock_case, execute_action, mock_failed):
        execute_action.return_value = mock_failed("The request could not be completed.")

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


class TestReplyModels:
    def test_reply_models_live_in_mocks(self):
        from zamp_sdk.mocks.models import MockCall, MockDecision

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
