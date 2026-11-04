"""Odd arguments never break a mockable call's payload."""

import inspect
import json
import math
from datetime import datetime
from decimal import Decimal

import pytest

from zamp_sdk.evals.models import MockCallInput
from zamp_sdk.evals.utils.eval_actions import build_traced_call_input


def _payload(**arguments):
    def target(**kwargs): ...

    call = build_traced_call_input("n", None, inspect.signature(target), (), arguments, "p")
    mock = MockCallInput(**call.model_dump(), input=call.args, call_id=call.invocation_id)
    return json.loads(json.dumps(mock.model_dump(mode="json")))


@pytest.mark.parametrize(
    "value",
    [
        b"\xff\xfe",
        {1, 2},
        object(),
        Decimal("1.5"),
        datetime(2020, 1, 1),
        float("inf"),
        math.nan,
        {1: "int key", None: "none key", (1, 2): "tuple key"},
        "é☃\x00" * 1000,
        ["x" * 10_000] * 100,
        lambda: 1,
        type,
    ],
)
def test_any_argument_value_makes_a_json_payload(value):
    payload = _payload(x=value)

    assert set(payload["input"]) == {"x"}


def test_a_self_containing_argument_is_a_placeholder():
    loop: list = []
    loop.append(loop)

    assert "list" in json.dumps(_payload(x=loop)["input"])


def test_deeply_nested_input_does_not_crash():
    nested: object = "leaf"
    for _ in range(500):
        nested = [nested]

    assert _payload(x=nested)["input"]["x"]


def test_a_credential_nested_in_a_list_of_dicts_is_dropped():
    payload = _payload(x=[{"password": "s", "ok": 1}], api_key="k")

    assert payload["input"] == {"x": [{"ok": 1}]}
