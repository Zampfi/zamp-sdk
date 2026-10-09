import asyncio

import pytest

from zamp_sdk import evals


@evals.external("erp.order", key="order_id")
async def fetch_order(order_id: str) -> dict:
    return {"id": order_id}


@evals.external("erp.order", key="order_id")
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


def sent(fixtures_and_trace):
    return [call.args[1] for call in fixtures_and_trace.call_args_list]


class TestOutsideAnEvalRun:
    async def test_async_runs_untouched(self, fixtures_and_trace):
        assert await load("O1") == {"order": {"id": "O1"}}

        fixtures_and_trace.assert_not_called()

    def test_sync_runs_untouched(self, fixtures_and_trace):
        assert load_sync("O1") == {"order": {"id": "O1"}}

        fixtures_and_trace.assert_not_called()

    async def test_async_raise_is_untouched(self, fixtures_and_trace):
        with pytest.raises(ValueError, match="bad"):
            await fail("bad")

        fixtures_and_trace.assert_not_called()

    def test_sync_raise_is_untouched(self, fixtures_and_trace):
        with pytest.raises(ValueError, match="bad"):
            fail_sync("bad")

        fixtures_and_trace.assert_not_called()


class TestReturns:
    async def test_async_runs_and_records_what_it_returned(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.side_effect = [returned({"id": "O1", "source": "fixture"}), None]

        result = await load("O1")

        assert result == {"order": {"id": "O1", "source": "fixture"}}
        inner, step = sent(fixtures_and_trace)
        assert fixtures_and_trace.call_args.args[0] == "eval_observed_step"
        assert step == {
            "name": "steps.load",
            "key": None,
            "invocation_id": step["invocation_id"],
            "parent": "test_observe.py:test_async_runs_and_records_what_it_returned",
            "args": {"order_id": "O1"},
            "outcome": {"kind": "returned", "value": result},
        }
        assert inner["parent"] == "steps.load"

    def test_sync_runs_and_records_what_it_returned(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.side_effect = [returned({"id": "O1"}), None]

        result = load_sync("O1")

        inner, step = sent(fixtures_and_trace)
        assert step["outcome"] == {"kind": "returned", "value": result}
        assert result == {"order": {"id": "O1"}}
        assert step["parent"] == "test_observe.py:test_sync_runs_and_records_what_it_returned"
        assert inner["parent"] == "steps.load"

    async def test_a_nested_step_names_the_step_around_it(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.side_effect = [returned({"id": "O1"}), None, None]

        await review("O1")

        inner, load_step, review_step = sent(fixtures_and_trace)
        assert (inner["parent"], load_step["parent"]) == ("steps.load", "steps.review")
        assert review_step["parent"] == "test_observe.py:test_a_nested_step_names_the_step_around_it"

    async def test_the_step_ends_with_the_call(self, eval_run, fixtures_and_trace, returned):
        fixtures_and_trace.side_effect = [returned({}), None, returned({})]

        await load("O1")
        await fetch_order("O2")

        assert sent(fixtures_and_trace)[2]["parent"] == "test_observe.py:test_the_step_ends_with_the_call"

    async def test_a_keyed_step_sends_its_key(self, eval_run, fixtures_and_trace):
        @evals.observe("steps.check", key="order_id")
        async def check(order_id: str) -> bool:
            return True

        fixtures_and_trace.return_value = None

        assert await check("O1") is True
        assert sent(fixtures_and_trace)[0]["key"] == "O1"

    @pytest.mark.xfail(
        strict=True,
        raises=UnicodeDecodeError,
        reason="SDK bug: to_json_value lets non-UTF-8 bytes raise instead of falling back to repr",
    )
    async def test_bytes_json_cannot_hold_are_recorded_as_their_repr(self, eval_run, fixtures_and_trace):
        @evals.observe("steps.render")
        async def render() -> bytes:
            return b"%PDF\xff"

        fixtures_and_trace.return_value = None

        assert await render() == b"%PDF\xff"
        assert sent(fixtures_and_trace)[0]["outcome"] == {"kind": "returned", "value": "b'%PDF\\xff'"}


class TestRaises:
    async def test_async_records_the_error_and_raises_it(self, eval_run, fixtures_and_trace):
        fixtures_and_trace.return_value = None

        with pytest.raises(ValueError, match="bad"):
            await fail("bad")

        (step,) = sent(fixtures_and_trace)
        assert step["outcome"] == {"kind": "raised", "type": "builtins.ValueError", "message": "bad"}

    def test_sync_records_the_error_and_raises_it(self, eval_run, fixtures_and_trace):
        fixtures_and_trace.return_value = None

        with pytest.raises(ValueError, match="bad"):
            fail_sync("bad")

        (step,) = sent(fixtures_and_trace)
        assert step["outcome"] == {"kind": "raised", "type": "builtins.ValueError", "message": "bad"}

    async def test_a_cancelled_step_records_nothing(self, eval_run, fixtures_and_trace):
        @evals.observe("steps.wait")
        async def wait():
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await wait()

        fixtures_and_trace.assert_not_called()


class TestOnTheExecutor:
    async def test_async_records_the_step_with_workflow_invocation_ids(
        self, executor_eval_run, fixtures_and_trace, returned, envelope
    ):
        fixtures_and_trace.side_effect = [envelope(returned({"id": "O1"})), envelope()]

        assert await load("O1") == {"order": {"id": "O1"}}
        assert [call["invocation_id"] for call in sent(fixtures_and_trace)] == ["workflow-uuid", "workflow-uuid"]

    async def test_a_failed_action_raises(self, executor_eval_run, fixtures_and_trace, returned, envelope):
        fixtures_and_trace.side_effect = [
            envelope(returned({"id": "O1"})),
            envelope(status="FAILED", error="no eval run"),
        ]

        with pytest.raises(RuntimeError, match="^eval_observed_step action-1 FAILED: no eval run$"):
            await load("O1")

    def test_sync_refuses_in_workflow_code(self, executor_eval_run, fixtures_and_trace):
        with pytest.raises(RuntimeError, match="steps.load: a sync function cannot reach eval_external_call"):
            load_sync("O1")

        fixtures_and_trace.assert_not_called()
