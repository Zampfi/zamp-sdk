"""Hand a blocker to the agent that ran this code, then continue with its answer.

:func:`escalate` is how authored code says it is stuck: a value it cannot find, a choice it
cannot make, a step a person has to approve. It goes to the agent that ran the code — the same
run, no new agent is started. That agent answers what it can, asks the user only for the rest
(with the summary, details and files on the card), and the code continues with the answers.
Questions marked ``requires_human`` always go to the user; the agent never answers them.

Neither runtime can wait for the answer, so the code continues in a new run, as it does after
:func:`request_user_input`:

**In a code-executor phase**, return the escalation. By default the same phase runs again with
the answers in its ``workflow_params``; read them with :func:`escalation_from`::

    class AuditAnswers(zamp_sdk.BaseWorkflow):
        async def workflow_impl(self, workflow_params):
            answer = zamp_sdk.escalation_from(workflow_params)
            if answer is None:
                return zamp_sdk.escalate(
                    "Line haul billed at $271.63; no base rate on file to recompute it",
                    details="Agreement pages searched: ...",
                    files=[agreement_path],
                    questions=[zamp_sdk.select_one(
                        "Which line haul does the agreement allow?",
                        [("accept_billed", "Accept $271.63"), ("flag", "Flag for review")],
                    )],
                )
            decision = answer.selected_option_for(0)   # an option id, whoever answered

Pass ``post_action=run_workflow(...)`` to continue in another phase instead. Anything the next
run needs must be saved before escalating and pointed at from ``workflow_params``.

**In a sandbox script**, the call does not return: the script exits, and is re-run with the
answers as its last argument; read them with :func:`parse_escalation`.

Answers come back in the shape each question asked for. When a person types text against an
options question, the agent turns it into the option it meant, and the words are kept in
``EscalationAnswer.human_text_for(i)`` — so a phase that reads ``selected_option_for(i)`` does
not see ``None`` and ask again.
"""

from __future__ import annotations

import json
import sys
from typing import NoReturn, Optional

from pydantic import ValidationError

from zamp_sdk.context import ExecutionHost, current_execution_host, resolve_context
from zamp_sdk.escalation.constants import ESCALATION_KEY, ESCALATION_WORKFLOW_PARAMS_KEY, SDK_ESCALATION_MARKER
from zamp_sdk.escalation.models import EscalationAnswer, EscalationFile, EscalationRequest
from zamp_sdk.logger import get_logger
from zamp_sdk.user_input.constants import (
    POST_ACTION_REQUIRED_FIELDS,
    POST_ACTION_RESUME_SCRIPT,
    POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
    SDK_USER_INPUT_EXIT_CODE,
)
from zamp_sdk.user_input.user_input import text_input
from zamp_sdk.user_input.utils import resume_script

logger = get_logger(__name__)


def escalate(
    summary: str,
    *,
    details: Optional[str] = None,
    files: Optional[list] = None,
    questions: Optional[list] = None,
    answer_schema: Optional[dict] = None,
    requires_human: bool = False,
    post_action: Optional[dict] = None,
) -> dict:
    """Hand what blocks this code to the agent that ran it.

    Args:
        summary: One line on what is blocking (at most 300 characters). Shown to the agent and,
            when it asks, at the top of the user's card.
        details: What the code saw that the answer may depend on (at most 16 KB): values,
            what it searched, what was missing.
        files: Files to look at, as absolute sandbox paths or ``{"path", "name"}`` dicts (at
            most 20). Shown to the agent and linked on the user's card.
        questions: What the code needs back, built with :func:`select_one`,
            :func:`multiple_choice` or :func:`text_input` (at most 10). A question dict with
            ``"requires_human": True`` always goes to the user. Omitted: one text question, the
            summary.
        answer_schema: A JSON Schema the answerer's structured ``value`` must match, read back
            with ``EscalationAnswer.value``.
        requires_human: Every question goes to the user; the agent only passes them on.
        post_action: What runs once everything is answered. In a phase: omitted, the same phase
            runs again; or :func:`run_workflow` for another. In a script: omitted, the script is
            re-run; or :func:`resume_script`.

    Returns:
        In a phase, the escalation to ``return`` from ``workflow_impl``; returning it ends the
        phase. A script does not return: it exits, and is re-run once everything is answered.

    Raises:
        ValueError: (in a phase) the escalation is not valid, or ``post_action`` is not one a
            phase can act on. A script prints the reason and exits with code 1 instead, so a
            broad ``except`` cannot carry on unanswered.
    """
    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        return _escalation_for_phase(summary, details, files, questions, answer_schema, requires_human, post_action)
    _escalate_and_exit_script(summary, details, files, questions, answer_schema, requires_human, post_action)


def escalation_from(workflow_params: dict) -> Optional[EscalationAnswer]:
    """The answers, when this phase was started after an :func:`escalate`.

    ``None`` on a phase that was not, so it doubles as a "was I answered?" check.
    """
    payload = (workflow_params or {}).get(ESCALATION_WORKFLOW_PARAMS_KEY)
    if not isinstance(payload, dict):
        return None
    return EscalationAnswer.model_validate(payload)


def parse_escalation(value: Optional[str]) -> Optional[EscalationAnswer]:
    """The answers the platform appended to a re-run script's command line.

    Pass the value of the flag the script resumes on; ``None`` on the first run.
    """
    if not value:
        return None
    try:
        data = json.loads(value)
    except (TypeError, ValueError) as exc:
        logger.warning("parse_escalation: value is not valid JSON", error=str(exc))
        return None
    if not isinstance(data, dict):
        logger.warning("parse_escalation: value is not a JSON object")
        return None
    return EscalationAnswer.model_validate(data)


def _escalation_for_phase(
    summary: str,
    details: Optional[str],
    files: Optional[list],
    questions: Optional[list],
    answer_schema: Optional[dict],
    requires_human: bool,
    post_action: Optional[dict],
) -> dict:
    if post_action is not None:
        _check_post_action(post_action, expected=POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW, builder="run_workflow(...)")
    request = _build_request(summary, details, files, questions, answer_schema, requires_human, post_action)
    logger.info("escalate: ending the phase", num_questions=len(request.questions))
    return {ESCALATION_KEY: request.model_dump(exclude_none=True)}


def _escalate_and_exit_script(
    summary: str,
    details: Optional[str],
    files: Optional[list],
    questions: Optional[list],
    answer_schema: Optional[dict],
    requires_human: bool,
    post_action: Optional[dict],
) -> NoReturn:
    try:
        post_action = _check_post_action(
            post_action or resume_script(), expected=POST_ACTION_RESUME_SCRIPT, builder="resume_script(...)"
        )
        post_action.setdefault("run_id", resolve_context().get("run_id"))
        request = _build_request(summary, details, files, questions, answer_schema, requires_human, post_action)
    except ValueError as exc:
        # Exit rather than raise: a broad except around the call would carry on unanswered.
        print(f"escalate failed: {exc}", file=sys.stderr)
        sys.exit(1)
    # The marker line is the contract the platform reads from stdout.
    print(f"{SDK_ESCALATION_MARKER} {json.dumps(request.model_dump(exclude_none=True))}", flush=True)
    logger.info("escalate: halting the script", num_questions=len(request.questions))
    sys.exit(SDK_USER_INPUT_EXIT_CODE)


def _build_request(
    summary: str,
    details: Optional[str],
    files: Optional[list],
    questions: Optional[list],
    answer_schema: Optional[dict],
    requires_human: bool,
    post_action: Optional[dict],
) -> EscalationRequest:
    try:
        return EscalationRequest.model_validate(
            {
                "summary": summary,
                "details": details,
                "files": [_file(f) for f in files or []],
                "questions": [q if isinstance(q, dict) else dict(q) for q in questions or [text_input(summary)]],
                "answer_schema": answer_schema,
                "requires_human": requires_human,
                "post_action": post_action,
            }
        )
    except ValidationError as exc:
        raise ValueError(f"escalate: {exc}") from exc


def _file(f: object) -> dict:
    if isinstance(f, str):
        return {"path": f}
    if isinstance(f, EscalationFile):
        return f.model_dump(exclude_none=True)
    if isinstance(f, dict):
        return f
    raise ValueError(f"escalate: a file is a path or a {{'path', 'name'}} dict, got {type(f).__name__}")


def _check_post_action(post_action: dict, *, expected: str, builder: str) -> dict:
    """The post-action, if this runtime can act on it; else ``ValueError`` naming the builder."""
    if post_action.get("type") != expected:
        raise ValueError(
            f"escalate: post_action must be {builder} here, got {post_action.get('type') or 'nothing'}. "
            f"A script is re-run and a phase's successor is started, so they are not interchangeable."
        )
    missing = [f for f in POST_ACTION_REQUIRED_FIELDS[expected] if not post_action.get(f)]
    if missing:
        raise ValueError(f"escalate: {builder} does not say what to start; missing {', '.join(missing)}")
    return post_action
