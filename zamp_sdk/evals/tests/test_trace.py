from zamp_sdk import evals
from zamp_sdk.evals.models import ExternalCall, ObservedStep

AT = "2026-10-08T10:00:00Z"


def traced(kind, name, outcome, key=None, n=1, **args):
    return {
        "kind": kind,
        "name": name,
        "key": key,
        "n": n,
        "invocation_id": f"{name}-{n}",
        "parent": "x.py:f",
        "args": args,
        "at": AT,
        "outcome": outcome,
    }


class TestReadTrace:
    async def test_sends_an_empty_request_to_the_read_trace_action(self, eval_run, fixtures_and_trace):
        fixtures_and_trace.return_value = {"lines": []}

        assert await evals.read_trace() == []

        fixtures_and_trace.assert_awaited_once_with("eval_read_trace", {})

    async def test_returns_the_lines_as_external_calls_and_observed_steps(
        self, eval_run, fixtures_and_trace, returned, raised
    ):
        fixtures_and_trace.return_value = {
            "lines": [
                traced("external", "erp.order", returned({"id": "O1"}), key="O1", order_id="O1"),
                traced("observe", "steps.load", raised("builtins.ValueError", "bad")),
            ]
        }

        external, observed = await evals.read_trace()

        assert isinstance(external, ExternalCall)
        assert (external.name, external.key, external.n, external.args) == ("erp.order", "O1", 1, {"order_id": "O1"})
        assert external.outcome.value == {"id": "O1"}
        assert isinstance(observed, ObservedStep)
        assert (observed.outcome.type, observed.outcome.message) == ("builtins.ValueError", "bad")

    async def test_an_external_call_can_carry_a_fixture_failure(self, eval_run, fixtures_and_trace, fixture_failed):
        failed = fixture_failed("FIXTURE_MISSING", "erp.order:O1#1: the item's fixture file has no key for this call")
        fixtures_and_trace.return_value = {"lines": [traced("external", "erp.order", failed, key="O1")]}

        (line,) = await evals.read_trace()

        assert line.outcome.code == "FIXTURE_MISSING"

    async def test_reads_through_the_gateway_envelope_on_the_executor(
        self, executor_eval_run, fixtures_and_trace, envelope, returned
    ):
        line = traced("observe", "steps.load", returned(None))
        fixtures_and_trace.return_value = envelope({"lines": [line]})

        (observed,) = await evals.read_trace()

        assert observed.name == "steps.load"
