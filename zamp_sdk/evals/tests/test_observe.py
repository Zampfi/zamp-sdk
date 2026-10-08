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


def sent(door):
    return [call.args[1] for call in door.call_args_list]


class TestOutsideAnEvalRun:
    async def test_async_runs_untouched(self, door):
        assert await load("O1") == {"order": {"id": "O1"}}

        door.assert_not_called()

    def test_sync_runs_untouched(self, door):
        assert load_sync("O1") == {"order": {"id": "O1"}}

        door.assert_not_called()

    async def test_async_raise_is_untouched(self, door):
        with pytest.raises(ValueError, match="bad"):
            await fail("bad")

        door.assert_not_called()

    def test_sync_raise_is_untouched(self, door):
        with pytest.raises(ValueError, match="bad"):
            fail_sync("bad")

        door.assert_not_called()


class TestReturns:
    async def test_async_runs_and_records_what_it_returned(self, eval_run, door, reply):
        door.side_effect = [reply(returns={"id": "O1", "source": "fixture"}), reply()]

        result = await load("O1")

        assert result == {"order": {"id": "O1", "source": "fixture"}}
        inner, step = sent(door)
        assert step == {
            "kind": "observe",
            "call_id": step["call_id"],
            "name": "steps.load",
            "key": None,
            "parent": "test_observe.py:test_async_runs_and_records_what_it_returned",
            "args": {"order_id": "O1"},
            "returns": result,
            "raises": None,
        }
        assert inner["parent"] == "steps.load"

    def test_sync_runs_and_records_what_it_returned(self, eval_run, door, reply):
        door.side_effect = [reply(returns={"id": "O1"}), reply()]

        result = load_sync("O1")

        inner, step = sent(door)
        assert step["returns"] == result == {"order": {"id": "O1"}}
        assert step["parent"] == "test_observe.py:test_sync_runs_and_records_what_it_returned"
        assert inner["parent"] == "steps.load"

    async def test_a_nested_step_names_the_step_around_it(self, eval_run, door, reply):
        door.side_effect = [reply(returns={"id": "O1"}), reply(), reply()]

        await review("O1")

        inner, load_step, review_step = sent(door)
        assert (inner["parent"], load_step["parent"]) == ("steps.load", "steps.review")
        assert review_step["parent"] == "test_observe.py:test_a_nested_step_names_the_step_around_it"

    async def test_the_step_ends_with_the_call(self, eval_run, door, reply):
        door.side_effect = [reply(returns={}), reply(), reply(returns={})]

        await load("O1")
        await fetch_order("O2")

        assert sent(door)[2]["parent"] == "test_observe.py:test_the_step_ends_with_the_call"

    async def test_a_keyed_step_sends_its_key(self, eval_run, door, reply):
        @evals.observe("steps.check", key="order_id")
        async def check(order_id: str) -> bool:
            return True

        door.return_value = reply()

        assert await check("O1") is True
        assert sent(door)[0]["key"] == "O1"

    async def test_bytes_json_cannot_hold_are_recorded_as_their_repr(self, eval_run, door, reply):
        @evals.observe("steps.render")
        async def render() -> bytes:
            return b"%PDF\xff"

        door.return_value = reply()

        assert await render() == b"%PDF\xff"
        assert sent(door)[0]["returns"] == "b'%PDF\\xff'"


class TestRaises:
    async def test_async_records_the_error_and_raises_it(self, eval_run, door, reply):
        door.return_value = reply()

        with pytest.raises(ValueError, match="bad"):
            await fail("bad")

        (step,) = sent(door)
        assert step["raises"] == {"type": "builtins.ValueError", "message": "bad"}
        assert step["returns"] is None

    def test_sync_records_the_error_and_raises_it(self, eval_run, door, reply):
        door.return_value = reply()

        with pytest.raises(ValueError, match="bad"):
            fail_sync("bad")

        (step,) = sent(door)
        assert step["raises"] == {"type": "builtins.ValueError", "message": "bad"}

    async def test_a_cancelled_step_records_nothing(self, eval_run, door):
        @evals.observe("steps.wait")
        async def wait():
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await wait()

        door.assert_not_called()


class TestOnTheExecutor:
    async def test_async_records_the_step_with_workflow_call_ids(self, executor_eval_run, door, reply):
        door.side_effect = [reply(returns={"id": "O1"}), reply()]

        assert await load("O1") == {"order": {"id": "O1"}}
        assert [call["call_id"] for call in sent(door)] == ["workflow-uuid", "workflow-uuid"]

    async def test_a_failed_door_call_propagates(self, executor_eval_run, door, reply):
        door.side_effect = [reply(returns={"id": "O1"}), RuntimeError("Action eval_door FAILED")]

        with pytest.raises(RuntimeError, match="eval_door"):
            await load("O1")

    def test_sync_refuses_in_workflow_code(self, executor_eval_run, door):
        with pytest.raises(RuntimeError, match="steps.load: a sync function cannot reach the eval door"):
            load_sync("O1")

        door.assert_not_called()
