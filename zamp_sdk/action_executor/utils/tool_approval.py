import json

from zamp_sdk.action_executor.constants import SDK_TOOL_APPROVAL_MARKER


def tool_approval_marker_line(policy_result_id: str, action_name: str) -> str:
    """The stdout line the platform parses to learn which approval a halted script waits on."""
    payload = {"policy_result_id": policy_result_id, "action_name": action_name}
    return f"{SDK_TOOL_APPROVAL_MARKER} {json.dumps(payload)}"
