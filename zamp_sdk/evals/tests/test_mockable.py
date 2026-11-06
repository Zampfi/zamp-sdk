from collections.abc import Callable

from pydantic import BaseModel

from zamp_sdk import evals
from zamp_sdk.mocks import mockable


class Order(BaseModel):
    id: str
    total: int


@mockable("erp.invoice")
async def fetch_invoice(invoice_id: str) -> Order:
    """Fetch one invoice."""
    return Order(id=invoice_id, total=-1)


@mockable("erp.untyped")
def fetch_untyped(x):
    return "live"


def sent(execute_action):
    return [call.args[1] for call in execute_action.call_args_list]


class TestMockable:
    async def test_outside_a_trial_runs_the_function(self, execute_action):
        assert await fetch_invoice("I1") == Order(id="I1", total=-1)

        execute_action.assert_not_called()

    async def test_in_a_trial_sends_only_name_input_output_schema_and_call_id(
        self, in_eval_trial, execute_action, returned
    ):
        execute_action.return_value = returned({"id": "I1", "total": 7})

        assert await fetch_invoice("I1") == Order(id="I1", total=7)

        action, call = execute_action.call_args.args
        assert action == "eval_external_call"
        assert call == {
            "name": "erp.invoice",
            "input": {"invoice_id": "I1"},
            "output_schema": Order.model_json_schema(),
            "call_id": call["call_id"],
        }
        assert call["call_id"]

    def test_without_an_annotation_sends_no_schema(self, in_eval_trial, execute_action, returned):
        execute_action.return_value = returned({"state": "down"})

        assert fetch_untyped(1) == {"state": "down"}

        (call,) = sent(execute_action)
        assert call["output_schema"] is None
        assert call["input"] == {"x": 1}

    async def test_a_return_type_without_a_json_schema_sends_none(self, in_eval_trial, execute_action, returned):
        @mockable("erp.callback")
        async def fetch_callback() -> Callable[[], None] | None:
            raise NotImplementedError

        execute_action.return_value = returned(None)

        await fetch_callback()

        (call,) = sent(execute_action)
        assert call["output_schema"] is None


class TestObserveUnchanged:
    async def test_observe_payload_has_no_mock_fields(self, in_eval_trial, execute_action):
        @evals.observe("steps.review")
        async def review(order_id: str) -> str:
            return "ok"

        execute_action.return_value = None

        assert await review("O1") == "ok"

        (step,) = sent(execute_action)
        assert "input" not in step
        assert "call_id" not in step
        assert "output_schema" not in step
        assert step["args"] == {"order_id": "O1"}
