"""Hand the questions blocking this code to the agent that ran it, then continue with the answers.

:func:`escalate` is called like :func:`request_user_input`: the same questions, built with
:func:`select_one`, :func:`multiple_choice` or :func:`text_input`, and the same post-actions. The
questions go to the agent that ran the code, in the same run, with ``context`` (what the code
saw), instead of to a person. The agent answers what it can and asks the user only for the rest.
A question marked ``"requires_human": True`` always goes to the user; the agent never answers it.
``requires_human=True`` marks every question.

Neither runtime can wait for the answers, so the code continues in a new run, as it does after
:func:`request_user_input`:

**In a code-executor phase**, return the escalation; returning it ends the phase. By default the
same phase runs again with the answers in its ``workflow_params``; read them with
:func:`escalation_from`::

    class AuditLineHaul(zamp_sdk.BaseWorkflow):
        async def workflow_impl(self, workflow_params):
            answer = zamp_sdk.escalation_from(workflow_params)
            if answer is None:
                return await zamp_sdk.escalate(
                    [zamp_sdk.select_one(
                        "Which line haul does the agreement allow?",
                        [("accept_billed", "Accept $271.63"), ("flag", "Flag for review")],
                    )],
                    context="Line haul billed at $271.63; no base rate on file. Searched: ...",
                )
            decision = answer.selected_option_for(0)   # an option id, whoever answered
            who = answer.answered_by_for(0)            # "agent", "human" or "parent_agent"

Pass ``post_action=run_workflow(...)`` to continue in another phase instead. Anything the next
run needs must be saved before escalating and pointed at from ``workflow_params``.

**In a sandbox script**, the call does not return: the script exits, and is re-run with the
answers on its command line; read them with :func:`parse_user_input`::

    answer = zamp_sdk.parse_user_input(args.answer)   # None on the first run
    if answer is None:
        await zamp_sdk.escalate(
            [zamp_sdk.text_input("Which PRO number is on the bill of lading?")],
            context="...",
            post_action=zamp_sdk.resume_script("--answer"),
        )

The answers come back in the shape each question asked for, whoever gave them. When a person
types text against an options question, the agent turns it into the option they meant, and
``human_text_for(i)`` keeps their words.
"""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn, Optional

from pydantic import ValidationError

from zamp_sdk.context import ExecutionHost, current_execution_host, resolve_context
from zamp_sdk.escalation.constants import ESCALATION_KEY, ESCALATION_WORKFLOW_PARAMS_KEY, SDK_ESCALATION_MARKER
from zamp_sdk.escalation.models import EscalationRequest
from zamp_sdk.logger import get_logger
from zamp_sdk.user_input.constants import (
    POST_ACTION_RESUME_SCRIPT,
    POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
    SDK_USER_INPUT_EXIT_CODE,
)
from zamp_sdk.user_input.models import UserInputResponse
from zamp_sdk.user_input.utils import response_under, resume_script, validated_post_action

logger = get_logger(__name__)


async def escalate(
    requests: list,
    *,
    context: Optional[str] = None,
    requires_human: bool = False,
    post_action: Optional[dict] = None,
) -> dict:
    """Hand the questions blocking this code to the agent that ran it, then stop.

    Args:
        requests: The questions, as for :func:`request_user_input`: built with
            :func:`select_one`, :func:`multiple_choice` or :func:`text_input` (at most 10). A
            question dict with ``"requires_human": True`` always goes to the user.
        context: What the code saw that the answers may depend on (at most 16 KB): the values,
            what it searched, what was missing. Shown to the agent and, when it asks, to the
            user. Save longer material to a file and put its path here.
        requires_human: Every question goes to the user; the agent only passes them on.
        post_action: What runs once everything is answered. In a **phase**: omitted, the same
            phase runs again; or :func:`run_workflow` for another phase. In a **script**:
            omitted, the script is re-run with the answers as its last argument; or
            :func:`resume_script` to name the flag they land on.

    Returns:
        In a phase, the escalation to ``return`` from ``workflow_impl``; returning it ends the
        phase. A script does not return: it exits, and is re-run once everything is answered.

    Raises:
        ValueError: (in a phase) the escalation is not valid, or ``post_action`` is not one a
            phase can act on. A script prints the reason and exits with code 1 instead, so a
            broad ``except`` cannot carry on unanswered.
    """
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        return _escalation_for_phase(requests, context, requires_human, post_action)
    _escalate_and_exit_script(requests, context, requires_human, post_action)


def escalation_from(workflow_params: dict) -> Optional[UserInputResponse]:
    """The answers, when this phase was started after an :func:`escalate`.

    The escalation counterpart of :func:`user_input_from`, read with the same accessors plus
    ``answered_by_for(i)`` and ``human_text_for(i)``. ``None`` on a phase that was not, so it
    doubles as a "was I answered?" check; a phase started by a ``request_user_input`` answer
    is not one.
    """
    return response_under(workflow_params, ESCALATION_WORKFLOW_PARAMS_KEY)


def _escalation_for_phase(
    requests: list,
    context: Optional[str],
    requires_human: bool,
    post_action: Optional[dict],
) -> dict:
    if post_action is not None:
        validated_post_action(
            post_action,
            caller="escalate",
            expected=POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
            builder="run_workflow(...)",
        )
    request = _build_request(requests, context, requires_human, post_action)
    logger.info("escalate: ending the phase", num_questions=len(request.questions))
    # No post-action means "run this phase again", which only the platform can resolve.
    return {ESCALATION_KEY: request.model_dump(exclude_none=True)}


def _escalate_and_exit_script(
    requests: list,
    context: Optional[str],
    requires_human: bool,
    post_action: Optional[dict],
) -> NoReturn:
    try:
        post_action = validated_post_action(
            post_action or resume_script(),
            caller="escalate",
            expected=POST_ACTION_RESUME_SCRIPT,
            builder="resume_script(...)",
        )
        post_action.setdefault("run_id", resolve_context().get("run_id"))
        request = _build_request(requests, context, requires_human, post_action)
        marker_line = f"{SDK_ESCALATION_MARKER} {json.dumps(request.model_dump(exclude_none=True))}"
    except Exception as exc:
        # Whatever went wrong, exit rather than raise: a raise is catchable, and an author's broad
        # ``except Exception`` around the call would carry on without the questions ever being sent.
        print(f"escalate failed: {exc}", file=sys.stderr)
        sys.exit(1)
    # The marker line is the contract the platform reads from stdout.
    print(marker_line, flush=True)
    logger.info("escalate: halting the script", num_questions=len(request.questions))
    sys.exit(SDK_USER_INPUT_EXIT_CODE)


def _build_request(
    requests: list,
    context: Optional[str],
    requires_human: bool,
    post_action: Optional[dict],
) -> EscalationRequest:
    questions = [_question(q) for q in requests]
    if requires_human:
        # SDK shorthand only: the platform reads the flag per question.
        questions = [{**q, "requires_human": True} for q in questions]
    try:
        return EscalationRequest.model_validate(
            {"questions": questions, "context": context, "post_action": post_action}
        )
    except ValidationError as exc:
        raise ValueError(f"escalate: {exc}") from exc


def _question(q: Any) -> dict:
    if isinstance(q, dict):
        return q
    try:
        return dict(q)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"escalate: a question is a dict built with select_one, multiple_choice or text_input, got {type(q).__name__}"
        ) from exc
