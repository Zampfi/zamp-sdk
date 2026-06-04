"""Human-in-the-loop from inside a sandboxed script.

A script running in the sandbox can pause mid-execution to ask the user a
structured question (text / single-select / multi-select), halt, and — once the
user answers — be **re-run** with the response so it can branch on the answer.

This is the *only* sanctioned way for generated code to raise a HITL. It does
**not** block the script waiting on the human (the platform action poll caps at
10 min and the sandbox itself caps at ~60 min, far short of a real human's
latency). Instead it:

1. Registers the question against the running task via the ``request_user_input``
   platform action (surfaces it to the user, marks the task as awaiting input).
2. Emits a sentinel marker line and exits the process, so the run halts.

When the user answers, the orchestrator re-runs the script with
``--hitl <response.json>`` (the ``resume_command`` captured below). Read that
file on startup to recover the answer and continue.

Example::

    import json, sys
    from zamp_sdk import request_user_input, text_input, select_one, read_user_input

    # Recover a prior answer if we were re-run after a HITL pause.
    answer = read_user_input()
    if answer is None:
        # First run — ask, then halt. Does not return.
        await request_user_input([
            select_one("Proceed with deletion?", [("yes", "Yes"), ("no", "No")]),
        ])
    else:
        choice = answer.selected_option_for(0)
        print(f"User chose: {choice}")
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, NoReturn, Optional

import structlog

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.context import resolve_context
from zamp_sdk.user_input.constants import (
    HITL_RESPONSE_FLAG,
    REQUEST_USER_INPUT_ACTION,
    SDK_USER_INPUT_EXIT_CODE,
    SDK_USER_INPUT_MARKER,
)
from zamp_sdk.user_input.models import UserInputResponse
from zamp_sdk.user_input.utils import build_options, default_resume_command

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Request builders — produce the request shape the platform expects
# ---------------------------------------------------------------------------


def text_input(question: str) -> dict:
    """A free-text question."""
    return {"input_type": "text", "question": question}


def select_one(question: str, options: list) -> dict:
    """A single-select question. ``options`` are ``(id, label)`` tuples, dicts, or InputOption."""
    return {"input_type": "select_one", "question": question, "options": build_options(options)}


def multiple_choice(question: str, options: list) -> dict:
    """A multi-select question. ``options`` are ``(id, label)`` tuples, dicts, or InputOption."""
    return {
        "input_type": "multiple_choice",
        "question": question,
        "options": build_options(options),
    }


# ---------------------------------------------------------------------------
# Response recovery (read by the re-run)
# ---------------------------------------------------------------------------


def read_user_input(argv: Optional[list[str]] = None) -> Optional[UserInputResponse]:
    """Return the HITL answer if this run was resumed with ``--hitl <file>``, else None.

    Parses ``argv`` (defaults to ``sys.argv``) for ``--hitl <path>`` and loads the
    JSON the orchestrator wrote there. The file shape is
    ``{"responses": [{"response": {...}}, ...]}`` — one entry per question asked.
    """
    args = argv if argv is not None else sys.argv
    path: Optional[str] = None
    # Read the LAST --hitl occurrence so a stale earlier flag never wins.
    for i, tok in enumerate(args):
        if tok == HITL_RESPONSE_FLAG and i + 1 < len(args):
            path = args[i + 1]
        elif tok.startswith(HITL_RESPONSE_FLAG + "="):
            path = tok.split("=", 1)[1]
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("read_user_input: failed to read response file", path=path, error=str(exc))
        return None
    if isinstance(data, dict) and "responses" in data:
        return UserInputResponse(responses=data.get("responses") or [])
    if isinstance(data, list):
        return UserInputResponse(responses=data)
    return UserInputResponse(responses=[data])


# ---------------------------------------------------------------------------
# request_user_input
# ---------------------------------------------------------------------------


async def request_user_input(
    requests: list,
    *,
    resume_command: Optional[list[str]] = None,
) -> NoReturn:
    """Ask the user one or more questions, then halt the script for HITL.

    Args:
        requests: A list of question dicts built via :func:`text_input`,
            :func:`select_one`, :func:`multiple_choice` (or raw dicts matching
            the platform's expected request shape).
        resume_command: The argv the orchestrator should re-run when the user
            answers. Defaults to the current ``sys.argv``; ``--hitl <response>``
            is appended automatically. Override to pin a specific entrypoint.

    Does not return — emits the sentinel marker and exits the process so the
    run halts. The orchestrator re-runs the script with ``--hitl`` once the
    user responds; recover the answer with :func:`read_user_input`.
    """
    normalized = [r if isinstance(r, dict) else dict(r) for r in requests]
    context = resolve_context()
    resume = {
        "command": list(resume_command) if resume_command else default_resume_command(),
        "cwd": os.getcwd(),
        "run_id": context.get("run_id"),
    }

    params: dict[str, Any] = {
        "requests": normalized,
        "context": context,
        "resume": resume,
    }

    try:
        await ActionExecutor.execute(
            REQUEST_USER_INPUT_ACTION,
            params,
            summary="Request human input from a sandboxed script",
        )
    except Exception as exc:  # noqa: BLE001
        # If we cannot register the HITL we must not silently continue — that
        # would run downstream steps without the human's answer. Surface it.
        logger.error("request_user_input: failed to register HITL", error=str(exc))
        print(f"request_user_input failed: {exc}", file=sys.stderr)
        sys.exit(1)

    marker_payload = {
        "hitl": True,
        "run_id": context.get("run_id"),
        "request_id": uuid.uuid4().hex,
        "num_questions": len(normalized),
    }
    # The marker is the contract the platform parses from stdout.
    print(f"{SDK_USER_INPUT_MARKER} {json.dumps(marker_payload)}", flush=True)
    logger.info("request_user_input: halting for HITL", num_questions=len(normalized))
    sys.exit(SDK_USER_INPUT_EXIT_CODE)
