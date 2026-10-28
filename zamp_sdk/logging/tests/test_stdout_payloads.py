"""The SDK's action logging prints nothing on stdout.

A call's input and result go to the live message only. On an executor worker stdout is a shared
operator log, and in a sandbox it would only repeat what the script already has. A failure is
still on record: in the closing block, in the step buffer, and in the action's Temporal history.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from zamp_sdk.action_executor.action_executor import ActionExecutor
from zamp_sdk.action_executor.models import ActionRequest
from zamp_sdk.context import ENV_EXECUTION_HOST, ExecutionHost
from zamp_sdk.logging.auto import fail_action_log
from zamp_sdk.logging.logging import emit_tool_result, emit_tool_use
from zamp_sdk.logging.models import EmitLogResult

SECRET_INPUT = {"api_key": "DUMMY-IN"}
SECRET_RESULT = {"access_token": "DUMMY-OUT"}


@pytest.fixture
def sent():
    """The blocks handed to the platform, without going near it."""
    with patch("zamp_sdk.logging.logging.emit_log", new_callable=AsyncMock) as emit_log:
        emit_log.return_value = EmitLogResult(ok=True)
        yield emit_log


@pytest.fixture(params=[None, ExecutionHost.ACTIONS_HUB], ids=["sandbox", "actions_hub"])
def on_any_host(request, monkeypatch):
    if request.param is None:
        monkeypatch.delenv(ENV_EXECUTION_HOST, raising=False)
    else:
        monkeypatch.setenv(ENV_EXECUTION_HOST, request.param)


async def test_nothing_about_a_successful_call_is_printed(on_any_host, sent):
    with capture_logs() as logs:
        block_id = await emit_tool_use("do_thing", input=SECRET_INPUT)
        await emit_tool_result(block_id, SECRET_RESULT, name="do_thing")

    assert logs == []


async def test_nothing_about_a_failed_call_is_printed(on_any_host, sent):
    with capture_logs() as logs:
        await fail_action_log("emit_1", "do_thing", RuntimeError("upstream down"))

    assert logs == []
    assert sent.await_args.args[0].content == "FAILED: upstream down", "the failure is in the closing block"


async def test_the_live_message_still_gets_the_payloads(on_any_host, sent):
    block_id = await emit_tool_use("do_thing", display_title="Doing", input=SECRET_INPUT)
    await emit_tool_result(block_id, SECRET_RESULT, name="do_thing")

    use_block, result_block = (call.args[0] for call in sent.await_args_list)
    assert (use_block.id, use_block.name, use_block.display_title) == (block_id, "do_thing", "Doing")
    assert "DUMMY-IN" in use_block.input_json
    assert "DUMMY-OUT" in result_block.content


async def test_a_failed_gateway_envelope_prints_nothing_and_its_error_reaches_the_block(on_any_host, sent):
    envelope = {"id": "a-1", "status": "FAILED", "result": None, "error": "not found"}
    request = ActionRequest(action_name="do_thing", params=SECRET_INPUT, log_action=True)

    with capture_logs() as logs:
        returned = await ActionExecutor._execute_via_gateway(request, AsyncMock(return_value=envelope))

    assert logs == []
    assert returned == envelope
    assert sent.await_args.args[0].content == "not found"
