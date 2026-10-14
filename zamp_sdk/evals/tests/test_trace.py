from zamp_sdk import evals
from zamp_sdk.evals.models import ExternalCall, ObservedStep

RECORDED_AT = "2026-10-08T10:00:00Z"


def trace_entry(kind, name, outcome, key=None, call_number=1, **args):
    return {
        "kind": kind,
        "name": name,
        "key": key,
        "call_number": call_number,
        "invocation_id": f"{name}-{call_number}",
        "parent": "x.py:f",
        "args": args,
        "recorded_at": RECORDED_AT,
        "outcome": outcome,
    }


class TestReadTrace:
    async def test_outside_an_eval_trial_is_empty_and_sends_nothing(self, execute_action):
        assert await evals.read_trace() == []

        execute_action.assert_not_called()

    async def test_sends_an_empty_request_to_the_read_trace_action(self, in_eval_trial, execute_action):
        execute_action.return_value = {"entries": []}

        assert await evals.read_trace() == []

        execute_action.assert_awaited_once_with("eval_read_trace", {})

    async def test_returns_the_entries_as_external_calls_and_observed_steps(
        self, in_eval_trial, execute_action, returned, raised
    ):
        execute_action.return_value = {
            "entries": [
                trace_entry("external_call", "erp.order", returned({"id": "O1"}), key="O1", order_id="O1"),
                trace_entry("observed_step", "steps.load", raised("builtins.ValueError", "bad")),
            ]
        }

        external, observed = await evals.read_trace()

        assert isinstance(external, ExternalCall)
        assert (external.name, external.key, external.call_number, external.args) == (
            "erp.order",
            "O1",
            1,
            {"order_id": "O1"},
        )
        assert external.outcome.value == {"id": "O1"}
        assert isinstance(observed, ObservedStep)
        assert (observed.outcome.type, observed.outcome.message) == ("builtins.ValueError", "bad")

    async def test_an_external_call_can_carry_a_fixture_failure(
        self, in_eval_trial, execute_action, fixture_lookup_failed
    ):
        failed = fixture_lookup_failed(
            "FIXTURE_MISSING", "erp.order:O1#1: the item's fixture file has no key for this call"
        )
        execute_action.return_value = {"entries": [trace_entry("external_call", "erp.order", failed, key="O1")]}

        (entry,) = await evals.read_trace()

        assert entry.outcome.code == "FIXTURE_MISSING"

    async def test_an_entry_keeps_any_name_key_and_error_type(self, in_eval_trial, execute_action, raised):
        execute_action.return_value = {
            "entries": [trace_entry("external_call", "Mail.Fetch", raised("TimeoutError", "late"), key="notes #2.msg")]
        }

        (entry,) = await evals.read_trace()

        assert (entry.name, entry.key, entry.outcome.type) == ("Mail.Fetch", "notes #2.msg", "TimeoutError")

    async def test_a_field_the_engine_adds_later_is_ignored(self, in_eval_trial, execute_action, returned):
        entry = trace_entry("external_call", "erp.order", {**returned(1), "took_ms": 3}, key="O1") | {"attempt": 2}
        execute_action.return_value = {"entries": [entry], "truncated": False}

        (read,) = await evals.read_trace()

        assert (read.key, read.outcome.value) == ("O1", 1)

    async def test_reads_through_the_action_response_on_the_executor(
        self, in_eval_trial_on_actions_hub, execute_action, action_response, returned
    ):
        entry = trace_entry("observed_step", "steps.load", returned(None))
        execute_action.return_value = action_response({"entries": [entry]})

        (observed,) = await evals.read_trace()

        assert observed.name == "steps.load"
