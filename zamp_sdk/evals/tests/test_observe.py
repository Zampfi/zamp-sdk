import asyncio

import pytest

from zamp_sdk import evals


@evals.external_call("erp.order", key_argument="order_id")
async def fetch_order(order_id: str) -> dict:
    return {"id": order_id}


@evals.external_call("erp.order", key_argument="order_id")
def fetch_order_sync(order_id: str) -> dict:
    return {"id": order_id}


@evals.observe("steps.load")
async def load(order_id: str) -> dict:
    return {"order": await fetch_order(order_id)}


@evals.observe("steps.load")
def load_sync(order_id: str) -> dict:
    return {"order": fetch_order_sync(order_id)}


@evals.observe("steps.review")
async def review(order_id: str) -> dict:
    return await load(order_id)


@evals.observe("steps.fail")
async def fail(reason: str):
    raise ValueError(reason)


@evals.observe("steps.fail")
def fail_sync(reason: str):
    raise ValueError(reason)


def sent(execute_action):
    return [call.args[1] for call in execute_action.call_args_list]


class TestOutsideAnEvalTrial:
    async def test_async_runs_untouched(self, execute_action):
        assert await load("O1") == {"order": {"id": "O1"}}

        execute_action.assert_not_called()

    def test_sync_runs_untouched(self, execute_action):
        assert load_sync("O1") == {"order": {"id": "O1"}}

        execute_action.assert_not_called()

    async def test_async_raise_is_untouched(self, execute_action):
        with pytest.raises(ValueError, match="bad"):
            await fail("bad")

        execute_action.assert_not_called()

    def test_sync_raise_is_untouched(self, execute_action):
        with pytest.raises(ValueError, match="bad"):
            fail_sync("bad")

        execute_action.assert_not_called()


class TestReturns:
    async def test_async_runs_and_records_what_it_returned(self, in_eval_trial, execute_action, returned):
        execute_action.side_effect = [returned({"id": "O1", "source": "fixture"}), None]

        result = await load("O1")

        assert result == {"order": {"id": "O1", "source": "fixture"}}
        inner, step = sent(execute_action)
        assert execute_action.call_args.args[0] == "eval_observed_step"
        assert step == {
            "name": "steps.load",
            "key": None,
            "invocation_id": step["invocation_id"],
            "parent": "test_observe.py:test_async_runs_and_records_what_it_returned",
            "args": {"order_id": "O1"},
            "outcome": {"kind": "returned", "value": result},
        }
        assert inner["parent"] == "steps.load"

    def test_sync_runs_and_records_what_it_returned(self, in_eval_trial, execute_action, returned):
        execute_action.side_effect = [returned({"id": "O1"}), None]

        result = load_sync("O1")

        inner, step = sent(execute_action)
        assert step["outcome"] == {"kind": "returned", "value": result}
        assert result == {"order": {"id": "O1"}}
        assert step["parent"] == "test_observe.py:test_sync_runs_and_records_what_it_returned"
        assert inner["parent"] == "steps.load"

    async def test_a_nested_step_names_the_step_around_it(self, in_eval_trial, execute_action, returned):
        execute_action.side_effect = [returned({"id": "O1"}), None, None]

        await review("O1")

        inner, load_step, review_step = sent(execute_action)
        assert (inner["parent"], load_step["parent"]) == ("steps.load", "steps.review")
        assert review_step["parent"] == "test_observe.py:test_a_nested_step_names_the_step_around_it"

    async def test_the_step_ends_with_the_call(self, in_eval_trial, execute_action, returned):
        execute_action.side_effect = [returned({}), None, returned({})]

        await load("O1")
        await fetch_order("O2")

        assert sent(execute_action)[2]["parent"] == "test_observe.py:test_the_step_ends_with_the_call"

    async def test_a_keyed_step_sends_its_key(self, in_eval_trial, execute_action):
        @evals.observe("steps.check", key_argument="order_id")
        async def check(order_id: str) -> bool:
            return True

        execute_action.return_value = None

        assert await check("O1") is True
        assert sent(execute_action)[0]["key"] == "O1"

    async def test_bytes_are_recorded_as_base64(self, in_eval_trial, execute_action):
        @evals.observe("steps.render")
        async def render() -> bytes:
            return b"%PDF\xff"

        execute_action.return_value = None

        assert await render() == b"%PDF\xff"
        assert sent(execute_action)[0]["outcome"] == {"kind": "returned", "value": "JVBERv8="}

    async def test_a_result_that_contains_itself_is_returned_and_recorded_as_its_type_only(
        self, in_eval_trial, execute_action
    ):
        @evals.observe("steps.build")
        async def build() -> list:
            lines: list = []
            lines.append(lines)
            return lines

        execute_action.return_value = None

        result = await build()

        assert result[0] is result
        assert sent(execute_action)[0]["outcome"] == {"kind": "returned", "value": "<list that contains itself>"}


class TestRaises:
    async def test_async_records_the_error_and_raises_it(self, in_eval_trial, execute_action):
        execute_action.return_value = None

        with pytest.raises(ValueError, match="bad"):
            await fail("bad")

        (step,) = sent(execute_action)
        assert step["outcome"] == {"kind": "raised", "type": "builtins.ValueError", "message": "bad"}

    def test_sync_records_the_error_and_raises_it(self, in_eval_trial, execute_action):
        execute_action.return_value = None

        with pytest.raises(ValueError, match="bad"):
            fail_sync("bad")

        (step,) = sent(execute_action)
        assert step["outcome"] == {"kind": "raised", "type": "builtins.ValueError", "message": "bad"}

    async def test_a_key_error_records_its_key_unquoted(self, in_eval_trial, execute_action):
        @evals.observe("steps.lookup")
        async def lookup():
            raise KeyError("order_id")

        execute_action.return_value = None

        with pytest.raises(KeyError):
            await lookup()

        (step,) = sent(execute_action)
        assert step["outcome"] == {"kind": "raised", "type": "builtins.KeyError", "message": "order_id"}

    async def test_async_raises_its_own_error_when_the_trace_send_fails(self, in_eval_trial, execute_action):
        execute_action.side_effect = ConnectionError("gateway down")

        with pytest.raises(ValueError, match="bad") as raised:
            await fail("bad")

        assert raised.value.__notes__ == ["steps.fail: the eval trace did not record this error, because gateway down"]

    def test_sync_raises_its_own_error_when_the_trace_send_fails(self, in_eval_trial, execute_action):
        execute_action.side_effect = ConnectionError("gateway down")

        with pytest.raises(ValueError, match="bad") as raised:
            fail_sync("bad")

        assert raised.value.__notes__ == ["steps.fail: the eval trace did not record this error, because gateway down"]

    async def test_a_cancelled_step_records_nothing(self, in_eval_trial, execute_action):
        @evals.observe("steps.wait")
        async def wait():
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await wait()

        execute_action.assert_not_called()


class TestOnTheExecutor:
    async def test_async_records_the_step_with_workflow_invocation_ids(
        self, in_eval_trial_on_actions_hub, execute_action, returned, action_response
    ):
        execute_action.side_effect = [action_response(returned({"id": "O1"})), action_response()]

        assert await load("O1") == {"order": {"id": "O1"}}
        assert [call["invocation_id"] for call in sent(execute_action)] == ["workflow-uuid", "workflow-uuid"]

    async def test_a_failed_action_raises(
        self, in_eval_trial_on_actions_hub, execute_action, returned, action_response
    ):
        execute_action.side_effect = [
            action_response(returned({"id": "O1"})),
            action_response(status="FAILED", error="no eval trial"),
        ]

        with pytest.raises(RuntimeError, match="^eval_observed_step action-1 FAILED: no eval trial$"):
            await load("O1")

    def test_sync_runs_untouched_outside_a_trial(self, on_actions_hub_outside_a_trial, execute_action):
        assert load_sync("O1") == {"order": {"id": "O1"}}

        execute_action.assert_not_called()

    def test_sync_refuses_in_workflow_code(self, in_eval_trial_on_actions_hub, execute_action):
        with pytest.raises(RuntimeError, match="^steps.load: a sync function .* make load_sync async$"):
            load_sync("O1")

        execute_action.assert_not_called()
