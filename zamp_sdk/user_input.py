"""Human-in-the-loop from inside a sandboxed script.

A script running in the AAv2 sandbox can pause mid-execution to ask the user a
structured question (text / single-select / multi-select), halt, and — once the
user answers — be **re-run** with the response so it can branch on the answer.

This is the *only* sanctioned way for generated code to raise a HITL. It does
**not** block the script waiting on the human (the platform action poll caps at
10 min and the sandbox itself caps at ~60 min, far short of a real human's
latency). Instead it:

1. Registers the question against the running task via the ``request_user_input``
   platform action (surfaces it to the user, sets the task to NEEDS_INPUT).
2. Emits a sentinel marker line and exits the process, so the AAv2 run halts.

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
from pydantic import BaseModel, Field

from zamp_sdk.action_executor import ActionExecutor

logger = structlog.get_logger(__name__)

REQUEST_USER_INPUT_ACTION = "request_user_input"

# Printed verbatim to stdout right before the script exits. The platform's
# sandbox-HITL plugin keys off this exact prefix to recognise that the script
# halted *for HITL* (as opposed to crashing) and should end the run in
# NEEDS_INPUT rather than CANCELED/FAILED.
SDK_USER_INPUT_MARKER = "__ZAMP_SDK_USER_INPUT__"

# Exit code used when halting for HITL. Secondary signal; the marker line is the
# primary one (survives regardless of how the host interprets the exit code).
SDK_USER_INPUT_EXIT_CODE = 42

# CLI flag the orchestrator appends when re-running the script with the answer.
HITL_RESPONSE_FLAG = "--hitl"

# Same env vars emit_log resolves — injected by the sandbox per exec.
ENV_CHANNEL_TYPE = "ZAMP_CHANNEL_TYPE"
ENV_CHANNEL_ID = "ZAMP_CHANNEL_ID"
ENV_STREAMING_ID = "ZAMP_STREAMING_ID"
ENV_MESSAGE_ID = "ZAMP_MESSAGE_ID"
ENV_TOOL_CALL_ID = "ZAMP_TOOL_CALL_ID"
ENV_RUN_ID = "ZAMP_RUN_ID"


# ---------------------------------------------------------------------------
# Request builders — mirror the platform's InputRequiredData shape
# ---------------------------------------------------------------------------


class InputOption(BaseModel):
    id: str
    label: str
    description: Optional[str] = None


def text_input(question: str) -> dict:
    """A free-text question."""
    return {"input_type": "text", "question": question}


def _options(options: list) -> list[dict]:
    out: list[dict] = []
    for opt in options:
        if isinstance(opt, InputOption):
            out.append(opt.model_dump(exclude_none=True))
        elif isinstance(opt, dict):
            out.append(opt)
        elif isinstance(opt, (tuple, list)) and len(opt) >= 2:
            out.append({"id": opt[0], "label": opt[1]})
        else:
            raise ValueError(f"Unsupported option: {opt!r} (use (id, label) or InputOption)")
    return out


def select_one(question: str, options: list) -> dict:
    """A single-select question. ``options`` are ``(id, label)`` tuples, dicts, or InputOption."""
    return {"input_type": "select_one", "question": question, "options": _options(options)}


def multiple_choice(question: str, options: list) -> dict:
    """A multi-select question. ``options`` are ``(id, label)`` tuples, dicts, or InputOption."""
    return {
        "input_type": "multiple_choice",
        "question": question,
        "options": _options(options),
    }


# ---------------------------------------------------------------------------
# Response recovery (read by the re-run)
# ---------------------------------------------------------------------------


class UserInputResponse(BaseModel):
    """The user's answer to a prior :func:`request_user_input`, recovered on re-run."""

    responses: list[dict] = Field(default_factory=list)

    def selected_option_for(self, index: int = 0) -> Optional[str]:
        """The selected option id for the *index*-th question (select_one)."""
        resp = self._response(index)
        return (resp or {}).get("selected_option")

    def text_for(self, index: int = 0) -> Optional[str]:
        """The free-text / custom answer for the *index*-th question."""
        resp = self._response(index)
        if not resp:
            return None
        return resp.get("custom_input") or resp.get("text")

    def _response(self, index: int) -> Optional[dict]:
        if index >= len(self.responses):
            return None
        item = self.responses[index] or {}
        return item.get("response") or item


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


def _resolve_context() -> dict[str, Any]:
    ctx = {
        "channel_type": os.environ.get(ENV_CHANNEL_TYPE),
        "channel_id": os.environ.get(ENV_CHANNEL_ID),
        "streaming_id": os.environ.get(ENV_STREAMING_ID),
        "message_id": os.environ.get(ENV_MESSAGE_ID),
        "tool_call_id": os.environ.get(ENV_TOOL_CALL_ID),
        "run_id": os.environ.get(ENV_RUN_ID),
    }
    return {k: v for k, v in ctx.items() if v}


def _strip_hitl_flag(argv: list[str]) -> list[str]:
    """Drop any existing ``--hitl <file>`` (or ``--hitl=<file>``) pair from argv.

    On a re-run the script's argv already contains ``--hitl <prev>``; the
    orchestrator appends a fresh one each round, so we must not let stale flags
    accumulate (which would make read_user_input read an old answer).
    """
    out: list[str] = []
    skip_next = False
    for tok in argv:
        if skip_next:
            skip_next = False
            continue
        if tok == HITL_RESPONSE_FLAG:
            skip_next = True
            continue
        if tok.startswith(HITL_RESPONSE_FLAG + "="):
            continue
        out.append(tok)
    return out


def _default_resume_command() -> list[str]:
    """The argv to re-run, with the interpreter prepended and stale --hitl removed.

    ``sys.argv`` omits the interpreter (``["main.py", ...]``), so re-running it
    verbatim would try to exec ``main.py`` as a program. Prepend
    ``sys.executable`` → ``["/usr/bin/python", "main.py", ...]``.
    """
    return [sys.executable, *_strip_hitl_flag(sys.argv)]


async def request_user_input(
    requests: list,
    *,
    resume_command: Optional[list[str]] = None,
) -> NoReturn:
    """Ask the user one or more questions, then halt the script for HITL.

    Args:
        requests: A list of question dicts built via :func:`text_input`,
            :func:`select_one`, :func:`multiple_choice` (or raw dicts matching
            the platform InputRequiredData shape).
        resume_command: The argv the orchestrator should re-run when the user
            answers. Defaults to the current ``sys.argv``; ``--hitl <response>``
            is appended automatically. Override to pin a specific entrypoint.

    Does not return — emits the sentinel marker and exits the process so the
    AAv2 run halts. The orchestrator re-runs the script with ``--hitl`` once the
    user responds; recover the answer with :func:`read_user_input`.
    """
    normalized = [r if isinstance(r, dict) else dict(r) for r in requests]
    context = _resolve_context()
    resume = {
        "command": list(resume_command) if resume_command else _default_resume_command(),
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
    # The marker is the contract the sandbox-HITL plugin parses from stdout.
    print(f"{SDK_USER_INPUT_MARKER} {json.dumps(marker_payload)}", flush=True)
    logger.info("request_user_input: halting for HITL", num_questions=len(normalized))
    sys.exit(SDK_USER_INPUT_EXIT_CODE)
