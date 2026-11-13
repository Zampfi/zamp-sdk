import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from zamp_sdk import ActionExecutor, mocks
from zamp_sdk.action_executor.utils.http_client import HttpClientError
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
    async def test_gate_7_no_answer_runs_the_body(self, in_mock_case, execute_action, decision):
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


class TestGate6TheAsk:
    async def test_gate_6_a_mockable_called_while_another_asks_is_still_asked(self, in_mock_case):
        started, release = asyncio.Event(), asyncio.Event()
        asked = []

        async def execute(action_name, params, **kwargs):
            asked.append(params["input"]["invoice_id"])
            if params["input"]["invoice_id"] == "held":
                started.set()
                await release.wait()
            return {"decision": "run_real"}

        with patch(f"{EXECUTOR}.ActionExecutor.execute", side_effect=execute):
            held = asyncio.create_task(fetch_invoice("held"))
            await started.wait()
            await fetch_invoice("other")
            release.set()
            await held

        assert asked == ["held", "other"]


def http_client_failing_first_post(posts: list[dict], status: int = 502):
    responses = iter(
        [
            HttpClientError("bad gateway", status_code=status),
            {"id": "action-2"},
        ]
    )

    def client(base_url, default_headers):
        http = AsyncMock()

        async def post(endpoint, data, **kwargs):
            posts.append(data)
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        http.post.side_effect = post
        http.get.return_value = {"status": "COMPLETED", "result": {"decision": "run_real"}}
        return http

    return client


class TestCall20SandboxAskRetries:
    async def test_call_20_a_retried_post_of_the_ask_reuses_its_call_id(self, in_mock_case, monkeypatch):
        monkeypatch.setenv("ZAMP_BASE_URL", "https://api.zamp.test")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "tok")
        posts: list[dict] = []

        with (
            patch(f"{EXECUTOR}.HttpClient", side_effect=http_client_failing_first_post(posts)),
            patch(f"{EXECUTOR}.asyncio.sleep", new=AsyncMock()),
        ):
            assert await fetch_invoice("I1") == Invoice(id="I1", total=-1)

        assert [post["action_name"] for post in posts] == ["mock_call", "mock_call"]
        assert posts[0]["params"]["call_id"] == posts[1]["params"]["call_id"]

    async def test_call_20_the_same_script_run_again_asks_with_another_call_id(
        self, in_mock_case, execute_action, run_real
    ):
        execute_action.return_value = run_real

        await fetch_invoice("I1")
        await fetch_invoice("I1")

        first, again = (awaited.args[1]["call_id"] for awaited in execute_action.await_args_list)
        assert first != again

    async def test_call_20_the_ask_is_sent_durably_with_the_server_retry_policy(self, in_mock_case, monkeypatch):
        monkeypatch.setenv("ZAMP_BASE_URL", "https://api.zamp.test")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "tok")
        run_real = AsyncMock(return_value={"decision": "run_real"})
        with patch(f"{EXECUTOR}.ActionExecutor._execute_action", new=run_real) as sent:
            await fetch_invoice("I1")

        assert sent.await_args.kwargs["execution_mode"] is None


class TestAskRunsThroughTheRealExecutorEntry:
    async def test_gate_6_real_execute_routes_the_ask_over_http_with_the_case_header(self, in_mock_case, monkeypatch):
        monkeypatch.setenv("ZAMP_BASE_URL", "https://api.zamp.test")
        monkeypatch.setenv("ZAMP_AUTH_TOKEN", "tok")
        headers = []

        def client(base_url, default_headers):
            headers.append(default_headers.get("X-MOCK-CASE-ID"))
            http = AsyncMock()
            http.post.return_value = {"id": "a"}
            http.get.return_value = {"status": "COMPLETED", "result": {"decision": "run_real"}}
            return http

        with patch(f"{EXECUTOR}.HttpClient", side_effect=client):
            await fetch_invoice("I1")
            await ActionExecutor.execute("erp_other", {"x": 1})

        assert headers == ["case-1", "case-1"]
