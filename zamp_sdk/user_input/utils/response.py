from __future__ import annotations

from typing import Optional

from zamp_sdk.user_input.models import UserInputResponse


def response_under(workflow_params: Optional[dict], key: str) -> Optional[UserInputResponse]:
    """The answers the platform put under ``key`` of a phase's ``workflow_params``.

    Behind :func:`user_input_from` and :func:`escalation_from`, which differ only in the key.
    ``None`` when the key is missing or holds something other than a dict: a phase that was
    not started by an answer.
    """
    payload = (workflow_params or {}).get(key)
    if not isinstance(payload, dict):
        return None
    return UserInputResponse(responses=payload.get("responses") or [])
