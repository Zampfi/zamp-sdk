import json

from zamp_sdk.action_executor.constants import SDK_TOOL_APPROVAL_MARKER


def tool_approval_marker_line(policy_result_id: str | None, action_name: str) -> str:
    """The stdout line the platform parses to learn which approval a halted script waits on."""
    payload = {"policy_result_id": policy_result_id, "action_name": action_name}
    return f"{SDK_TOOL_APPROVAL_MARKER} {json.dumps(payload)}"


class ToolApprovalRequired(BaseException):  # noqa: N818 - a halt signal, not an error
    """A tool call needs a human's approval, so the calling code must stop here.

    Raised on the code-executor (ActionsHub) host, where ``sys.exit`` is forbidden inside a
    workflow; the executor catches it and ends the phase. It derives from ``BaseException``,
    not ``Exception``, so an author's ``except Exception`` around the call cannot swallow it and
    carry on without the approval. A sandbox script halts with ``sys.exit`` instead.
    """

    def __init__(self, policy_result_id: str | None, action_name: str) -> None:
        self.policy_result_id = policy_result_id
        self.action_name = action_name
        super().__init__(
            f"Tool call {action_name!r} needs approval (policy_result_id={policy_result_id}); "
            "stopping until it is approved."
        )
