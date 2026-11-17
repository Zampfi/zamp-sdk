import asyncio

import pytest
from pydantic import BaseModel

from zamp_sdk import mocks
from zamp_sdk.mocks import mockable

EXECUTOR = "zamp_sdk.action_executor.action_executor"


class Invoice(BaseModel):
    id: str
    total: int


bodies_run: list[str] = []


@mockable("qa.invoice")
async def fetch_invoice(invoice_id: str) -> Invoice:
    bodies_run.append(invoice_id)
    return Invoice(id=invoice_id, total=-1)


@mockable("qa.invoice")
def fetch_invoice_sync(invoice_id: str) -> Invoice:
    bodies_run.append(invoice_id)
    return Invoice(id=invoice_id, total=-1)


async def both(invoice_id: str) -> list[Invoice | Exception]:
    outcomes: list[Invoice | Exception] = []
    for call in (fetch_invoice, fetch_invoice_sync):
        try:
            result = call(invoice_id)
            outcomes.append(await result if asyncio.iscoroutine(result) else result)
        except Exception as error:
            outcomes.append(error)
    return outcomes


@pytest.fixture(autouse=True)
def no_body_run_yet():
    bodies_run.clear()


def answered(outcome: dict) -> dict:
    return {"decision": "answered", "outcome": outcome}


class TestGate7BodyRunsOnlyOnRunReal:
    @pytest.mark.parametrize(
        "decision",
        [
            answered({"kind": "returned", "value": {"id": "I1", "total": 7}}),
            answered({"kind": "raised", "type": "builtins.TimeoutError", "message": "timed out"}),
            answered({"kind": "raised", "type": "nowhere.Unknown", "message": "m"}),
            answered({"kind": "mock_failed", "message": "The request could not be completed."}),
            {"decision": "skipped"},
            {"decision": "answered"},
            "run_real",
            None,
        ],
    )
    async def test_gate_7_a_reply_that_is_not_run_real_does_not_run_the_body(
        self, in_mock_case, execute_action, decision
    ):
        execute_action.return_value = decision

        await both("I1")

        assert bodies_run == []
        assert execute_action.await_count == 2

    async def test_gate_7_run_real_runs_the_body_once_per_call(self, in_mock_case, execute_action, run_real):
        execute_action.return_value = run_real

        assert await both("I1") == [Invoice(id="I1", total=-1)] * 2
        assert bodies_run == ["I1", "I1"]

    async def test_gate_7_an_unknown_reply_is_mock_failed_error(self, in_mock_case, execute_action):
        execute_action.return_value = {"decision": "skipped"}

        assert [type(outcome) for outcome in await both("I1")] == [mocks.MockFailedError] * 2

    async def test_gate_7_a_returned_value_that_does_not_fit_the_return_type_is_mock_failed_error(
        self, in_mock_case, execute_action
    ):
        execute_action.return_value = answered({"kind": "returned", "value": {"id": "I1", "total": "SECRET-x"}})

        outcomes = await both("I1")

        assert [type(outcome) for outcome in outcomes] == [mocks.MockFailedError] * 2, outcomes
        assert bodies_run == []


class TestGate8WhereTheCaseComesFrom:
    async def test_gate_8_env_set_asks(self, in_mock_case, execute_action, run_real):
        execute_action.return_value = run_real

        await fetch_invoice("I1")

        assert execute_action.await_args.args[1]["case_id"] == "case-1"

    @pytest.mark.parametrize("value", [None, ""])
    async def test_gate_8_env_unset_or_empty_does_not_ask(self, monkeypatch, execute_action, value):
        if value is not None:
            monkeypatch.setenv("ZAMP_MOCK_CASE_ID", value)

        assert await both("I1") == [Invoice(id="I1", total=-1)] * 2
        execute_action.assert_not_awaited()

    async def test_gate_8_context_field_on_the_actions_hub_asks(
        self, in_mock_case_on_actions_hub, execute_action, run_real
    ):
        execute_action.return_value = run_real

        await fetch_invoice("I1")

        assert execute_action.await_args.args[1]["case_id"] == "case-1"

    async def test_gate_8_actions_hub_without_the_field_does_not_ask(
        self, on_actions_hub_without_trial_or_case, execute_action
    ):
        await fetch_invoice("I1")

        execute_action.assert_not_awaited()
