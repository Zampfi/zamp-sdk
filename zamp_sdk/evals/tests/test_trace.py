import pytest
from pydantic import ValidationError

from zamp_sdk import evals


def sent_call(door):
    return door.call_args.args[1]


def line(name, key=None, n=1, **args):
    return evals.TraceLine(kind="external", name=name, key=key, n=n, parent="x.py:f", args=args)


@pytest.fixture
def trace():
    return evals.Trace(
        lines=[
            line("erp.token"),
            line("erp.attachment", key="ATT1", attachment_id="ATT1", realm="prod"),
            line("erp.attachment", key="ATT2", attachment_id="ATT2", realm="prod"),
            line("erp.approve", n=1),
            line("erp.approve", n=2),
        ]
    )


class TestTraceLine:
    def test_id_is_name_and_n(self):
        assert line("erp.approve", n=2).id == "erp.approve#2"

    def test_id_carries_the_key(self):
        assert line("erp.attachment", key="ATT1").id == "erp.attachment:ATT1#1"

    def test_rejects_an_unknown_field(self):
        with pytest.raises(ValidationError):
            evals.TraceLine(kind="external", name="erp.token", n=1, parent="p", args={}, extra=True)

    def test_rejects_a_bad_name(self):
        with pytest.raises(ValidationError):
            line("Token")


class TestFind:
    def test_by_name(self, trace):
        assert [found.id for found in trace.find("erp.attachment")] == [
            "erp.attachment:ATT1#1",
            "erp.attachment:ATT2#1",
        ]

    def test_by_key(self, trace):
        assert [found.id for found in trace.find("erp.attachment", key="ATT2")] == ["erp.attachment:ATT2#1"]

    def test_by_args(self, trace):
        assert [found.id for found in trace.find("erp.attachment", attachment_id="ATT1")] == ["erp.attachment:ATT1#1"]

    def test_nothing_found(self, trace):
        assert trace.find("erp.reject") == []


class TestOne:
    def test_the_only_line(self, trace):
        assert trace.one("erp.token").id == "erp.token#1"

    def test_raises_on_several(self, trace):
        with pytest.raises(LookupError, match="erp.approve: expected one trace line, found 2"):
            trace.one("erp.approve")

    def test_raises_on_none(self, trace):
        with pytest.raises(LookupError, match="erp.reject: expected one trace line, found 0"):
            trace.one("erp.reject")


class TestLast:
    def test_the_last_line(self, trace):
        assert trace.last("erp.approve").id == "erp.approve#2"

    def test_raises_on_none(self, trace):
        with pytest.raises(LookupError, match="erp.reject: no trace line"):
            trace.last("erp.reject")


class TestReadTrace:
    async def test_reads_through_the_door(self, eval_run, door):
        external = {"kind": "external", "name": "erp.order", "key": "O1", "n": 1, "parent": "x.py:f", "args": {}}
        observe = {"kind": "observe", "name": "steps.load", "n": 1, "parent": "x.py:f", "args": {}}
        door.return_value = {"lines": [{**external, "returns": {"id": "O1"}}, observe]}

        trace = await evals.read_trace()

        action, call = door.call_args.args
        assert action == "eval_door"
        assert call == {"kind": "read_trace", "call_id": call["call_id"]}
        assert [found.id for found in trace.lines] == ["erp.order:O1#1", "steps.load#1"]
        assert trace.one("erp.order", key="O1").returns == {"id": "O1"}

    async def test_reads_through_the_gateway_on_the_executor(self, executor_eval_run, gateway, envelope):
        line = {"kind": "observe", "name": "steps.load", "n": 1, "parent": "x.py:f", "args": {}}
        gateway.return_value = envelope({"lines": [line]})

        trace = await evals.read_trace()

        assert sent_call(gateway) == {"kind": "read_trace", "call_id": "workflow-uuid"}
        assert trace.one("steps.load").id == "steps.load#1"
