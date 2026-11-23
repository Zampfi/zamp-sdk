import json

from zamp_sdk.action_executor.constants import SDK_TOOL_APPROVAL_MARKER
from zamp_sdk.action_executor.utils.tool_approval import tool_approval_marker_line


def test_marker_line_is_the_marker_then_a_json_payload():
    line = tool_approval_marker_line("pr-1", "send_email")
    assert line.startswith(SDK_TOOL_APPROVAL_MARKER + " ")
    assert json.loads(line.removeprefix(SDK_TOOL_APPROVAL_MARKER + " ")) == {
        "policy_result_id": "pr-1",
        "action_name": "send_email",
    }
