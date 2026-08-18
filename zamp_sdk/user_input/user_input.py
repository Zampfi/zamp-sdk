"""Ask the user a question and continue with their answer.

:func:`request_user_input` presents one or more structured questions (text,
single-select, multi-select, or file upload). *How* your code continues afterwards
depends on what is running it, because the two runtimes differ in what they can do:

**In a sandbox script** (the default) a process cannot sit idle for a human, so the call
halts the script — it does **not** block and **does not return**. When the user answers,
the script is **re-run** with the answer supplied on the command line; recover it with
:func:`parse_user_input`. Keep any state you need across the pause on disk or thread it
through your own CLI flags (see :func:`resume_script`)::

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

**In a code-executor workflow** a Temporal workflow cannot wait on a human either, so the
call registers the question and comes back, and the phase then **ends itself**. Once the
user answers, the platform starts the **next phase** you named — a fresh run with the
answer in its ``workflow_params``; read it with :func:`user_input_from`. Anything that
phase needs must be checkpointed before you ask (the filesystem / dataset actions) and
pointed at from ``workflow_params`` (see :func:`run_workflow`)::

    class ConfirmCategory(zamp_sdk.BaseWorkflow):
        async def workflow_impl(self, workflow_params):
            state_path = await save_checkpoint(...)      # must survive the pause
            await zamp_sdk.request_user_input(
                [zamp_sdk.select_one("Category is Consulting — correct?",
                                     [("yes", "Yes"), ("no", "No")])],
                post_action=zamp_sdk.run_workflow(
                    "ApplyCategoryDecision",
                    code_directory_path="invoice_process/",
                    workflow_params={"checkpoint": state_path},
                ),
            )
            return zamp_sdk.AWAITING_USER_INPUT   # halted, not finished

    class ApplyCategoryDecision(zamp_sdk.BaseWorkflow):
        async def workflow_impl(self, workflow_params):
            answer = zamp_sdk.user_input_from(workflow_params)
            ...

Neither runtime hands the answer back to the caller — a script exits and is re-run, a
phase ends and its successor is started — so both recover it at the top of the new run.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import NoReturn, Optional

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.context import ExecutionHost, current_execution_host, resolve_context
from zamp_sdk.logger import get_logger
from zamp_sdk.user_input.constants import (
    POST_ACTION_REQUIRED_FIELDS,
    POST_ACTION_RESUME_SCRIPT,
    POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
    REQUEST_USER_INPUT_ACTION,
    SDK_USER_INPUT_EXIT_CODE,
    SDK_USER_INPUT_MARKER,
    USER_INPUT_WORKFLOW_PARAMS_KEY,
)
from zamp_sdk.user_input.models import UserInputResponse
from zamp_sdk.user_input.utils import build_options, resume_script

logger = get_logger(__name__)


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


def _validated_post_action(post_action: Optional[dict], *, expected: str, builder: str) -> dict:
    """The post-action this runtime can act on, or ``ValueError`` naming the builder to use.

    Rejected before the question is registered, because the reverse order gives the one
    failure here that is silent: a recorded question, asked of a real person, that nothing can
    ever act on when they answer. The platform validates the payload again when it stores it;
    this is the early copy, and the only one that can name the builder to call instead.
    """
    if not post_action or post_action.get("type") != expected:
        actual = (post_action or {}).get("type")
        raise ValueError(
            f"request_user_input: post_action must be {builder} here, got "
            f"{actual or 'nothing'}. The two runtimes carry on differently — a script is "
            f"re-run, a workflow's next phase is started — so a post-action is not "
            f"interchangeable between them."
        )
    missing = [f for f in POST_ACTION_REQUIRED_FIELDS[expected] if not post_action.get(f)]
    if missing:
        raise ValueError(
            f"request_user_input: {builder} does not say what to start — missing "
            f"{', '.join(missing)}. Nothing would happen when the user answers."
        )
    return post_action


async def request_user_input(
    requests: list,
    *,
    post_action: Optional[dict] = None,
) -> None:
    """Ask the user one or more questions, then stop.

    Args:
        requests: A list of question dicts built via :func:`text_input`,
            :func:`select_one`, :func:`multiple_choice` (or raw dicts matching
            the platform's expected request shape).
        post_action: What should be started once the user answers. It differs by runtime and
            is not interchangeable between them.
            In a **script**: :func:`resume_script` — pass the flag the answer should land
            on, e.g. ``resume_script("--country")``; omitted, it defaults to re-running the
            current invocation with the answer as a trailing argument.
            In a **workflow**: :func:`run_workflow` — name the phase to run next, e.g.
            ``run_workflow("ApplyCategoryDecision", code_directory_path=...)``. Required
            there; there is no sensible default, since only the author knows the next phase.

    Returns:
        Nothing you can use, in either runtime — the answer never comes back to this caller.
        A script does not come back at all: it exits here and is re-run, which is why
        ``NoReturn`` sits on ``_ask_and_exit_script``, where it is literally true. A workflow
        does return, with no value, so the phase can end itself on the next line with
        ``return AWAITING_USER_INPUT``. Recover the answer at the top of the new run:
        :func:`parse_user_input` in a script, :func:`user_input_from` in a workflow.

    Raises:
        ValueError: ``post_action`` is not the one this runtime can act on, or does not say
            what to start.
    """
    normalized = [r if isinstance(r, dict) else dict(r) for r in requests]

    if current_execution_host() is ExecutionHost.ACTIONS_HUB:
        await _ask_and_end_phase(normalized, post_action)
    else:
        await _ask_and_exit_script(normalized, post_action)


async def _ask_and_exit_script(requests: list[dict], post_action: Optional[dict]) -> NoReturn:
    """Register the question(s), print the marker, exit. Does not return.

    A process cannot sit idle for a human, so the script ends here and the platform re-runs it
    with the answer on its command line. Defaults to re-running the current invocation, which
    is what a script almost always wants and is derivable from ``sys.argv``.
    """
    context = resolve_context()
    try:
        post_action = _validated_post_action(
            post_action or resume_script(),
            expected=POST_ACTION_RESUME_SCRIPT,
            builder="resume_script(...)",
        )
        # Carry the run_id from context so the platform can correlate the re-run.
        post_action.setdefault("run_id", context.get("run_id"))

        await ActionExecutor.execute(
            REQUEST_USER_INPUT_ACTION,
            {"requests": requests, "context": context, "post_action": post_action},
            summary="Request human input from a sandboxed script",
        )
    except Exception as exc:
        # Whether the post-action was unusable or the platform call failed, we must not
        # silently continue — that would run downstream steps without the human's answer.
        # Exiting rather than raising, because a raise is catchable: an author's broad
        # ``except Exception`` around the ask would swallow it and carry on unanswered.
        logger.error("request_user_input: failed to register HITL", error=str(exc))
        print(f"request_user_input failed: {exc}", file=sys.stderr)
        sys.exit(1)

    marker_payload = {
        "hitl": True,
        "run_id": context.get("run_id"),
        "request_id": uuid.uuid4().hex,
        "num_questions": len(requests),
    }
    # The marker is the contract the platform parses from stdout.
    print(f"{SDK_USER_INPUT_MARKER} {json.dumps(marker_payload)}", flush=True)
    logger.info("request_user_input: halting for HITL", num_questions=len(requests))
    sys.exit(SDK_USER_INPUT_EXIT_CODE)


async def _ask_and_end_phase(requests: list[dict], post_action: Optional[dict]) -> None:
    """Register the question(s) so the calling phase can end itself. Returns nothing.

    A workflow cannot wait on a human any more than a process can, so the run stops when this
    phase returns, and the platform starts the phase named in ``post_action`` once the user
    answers — with the answer in its ``workflow_params``.

    Ending the phase is left to the author's own ``return AWAITING_USER_INPUT`` rather than
    done from here: the statement that ends a phase stays visible in the phase. If
    registration fails the exception propagates and the phase fails, which is what we want —
    a phase that returned quietly with no question recorded is a run nobody can answer and
    nothing will restart.
    """
    post_action = _validated_post_action(
        post_action,
        expected=POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
        builder="run_workflow(...)",
    )
    # channel_context is injected server-side from the verified execution token on this path,
    # so — unlike the script path — nothing about the calling task/conversation is sent here.
    await ActionExecutor.execute(
        REQUEST_USER_INPUT_ACTION,
        {"requests": requests, "post_action": post_action},
        summary="Ask the user and halt until the next phase is started",
    )
    logger.info(
        "request_user_input: halting for HITL",
        num_questions=len(requests),
        next_phase=post_action.get("workflow_name"),
    )


def user_input_from(workflow_params: dict) -> Optional[UserInputResponse]:
    """The answer, when this phase was started by a ``request_user_input`` post-action.

    The workflow counterpart of :func:`parse_user_input`. ``None`` on a phase that was not
    started by an answer, so it doubles as a "was I resumed?" check::

        answer = zamp_sdk.user_input_from(workflow_params)
        if answer is not None:
            decision = answer.selected_option_for(0)

    Read answers by index with ``.selected_option_for(i)`` / ``.text_for(i)`` /
    ``.selected_options_for(i)`` — the same accessors the script path uses.
    """
    payload = (workflow_params or {}).get(USER_INPUT_WORKFLOW_PARAMS_KEY)
    if not isinstance(payload, dict):
        return None
    return UserInputResponse(responses=payload.get("responses") or [])
