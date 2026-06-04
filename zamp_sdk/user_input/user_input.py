"""Ask the user a question from a running script, then resume with the answer.

:func:`request_user_input` presents one or more structured questions (text,
single-select, multi-select, or file upload) to the user and halts the script —
it does **not** block waiting for the human. When the user answers, the script is
**re-run** with the answer supplied on the command line; recover it with
:func:`parse_user_input`.

Because the script is re-run rather than resumed in place, keep any state you need
across the pause on disk, or carry it through your own CLI flags (see
:func:`resume_script`). A ``request_user_input`` call does not return.

Example::

    import argparse, asyncio
    from zamp_sdk import (
        request_user_input, select_one, parse_user_input, resume_script,
    )

    async def main():
        p = argparse.ArgumentParser()
        p.add_argument("--country")          # filled by the platform on resume
        args = p.parse_args()

        answer = parse_user_input(args.country)   # None on the first run
        if answer is None:
            # First run — ask, then halt. Does not return.
            await request_user_input(
                [select_one("Pick a country", [("us", "US"), ("eu", "EU")])],
                post_action=resume_script("--country"),
            )
        else:
            print(f"User chose: {answer.selected_option_for(0)}")

    asyncio.run(main())
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, NoReturn, Optional

import structlog

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.context import resolve_context
from zamp_sdk.user_input.constants import (
    REQUEST_USER_INPUT_ACTION,
    SDK_USER_INPUT_EXIT_CODE,
    SDK_USER_INPUT_MARKER,
)
from zamp_sdk.user_input.models import UserInputResponse
from zamp_sdk.user_input.utils import build_options, resume_script

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


def parse_user_input(value: Optional[str]) -> Optional[UserInputResponse]:
    """Parse the HITL answer the platform appended to the resume command.

    Pass the value of the flag you resumed on (e.g. ``args.country``):

    - On the **first** run that flag is unset, so ``None`` in → ``None`` out — a
      convenient "have we been answered yet?" check.
    - On a **resume** it's the JSON the platform appended
      (``{"responses": [{"response": {...}}, ...]}``); returns a
      :class:`UserInputResponse`. Read answers by index with
      ``.selected_option_for(i)`` / ``.text_for(i)`` /
      ``.selected_options_for(i)`` / ``.files_for(i)``.
    """
    if not value:
        return None
    try:
        data = json.loads(value)
    except (TypeError, ValueError) as exc:
        logger.warning("parse_user_input: value is not valid JSON", error=str(exc))
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
    post_action: Optional[dict] = None,
) -> NoReturn:
    """Ask the user one or more questions, then halt the script for HITL.

    Args:
        requests: A list of question dicts built via :func:`text_input`,
            :func:`select_one`, :func:`multiple_choice` (or raw dicts matching
            the platform's expected request shape).
        post_action: What to do once the user answers. Build it with
            :func:`resume_script` (the only post-action today) — pass the flag the
            answer should land on, e.g. ``resume_script("--country")``. If omitted,
            defaults to ``resume_script()`` (re-run the current invocation; the
            answer arrives as a trailing positional argument).

    Does not return — emits the sentinel marker and exits the process so the
    run halts. The post-action runs once the user responds (resume_script re-runs
    the script); recover the answer with :func:`parse_user_input`.
    """
    normalized = [r if isinstance(r, dict) else dict(r) for r in requests]
    context = resolve_context()
    if post_action is None:
        post_action = resume_script()
    # Carry the run_id from context so the platform can correlate the re-run.
    post_action.setdefault("run_id", context.get("run_id"))

    params: dict[str, Any] = {
        "requests": normalized,
        "context": context,
        "post_action": post_action,
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
