from __future__ import annotations

import os
import sys
from typing import Any, Optional

from zamp_sdk.user_input.constants import (
    POST_ACTION_RESUME_SCRIPT,
    POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
)


def resume_command_with(*flags: str) -> list[str]:
    """Build a re-run command: the current invocation plus the given flag(s).

    Internal helper behind :func:`resume_script`. ``sys.argv`` omits the
    interpreter (``["main.py", ...]``); we prepend ``sys.executable`` so the
    re-run is a valid ``python main.py ...`` invocation. On a re-run ``sys.argv``
    already carries the earlier ``--flag '<json>'`` pairs, so threading it keeps
    every prior answer on the command line (sequential HITLs need no checkpoint).
    """
    return [sys.executable, *sys.argv, *flags]


def default_resume_command() -> list[str]:
    """The current invocation, ready to re-run (interpreter prepended)."""
    return resume_command_with()


def resume_script(
    *flags: str,
    command: Optional[list[str]] = None,
    cwd: Optional[str] = None,
) -> dict[str, Any]:
    """Build the ``resume_script`` post-action — re-run this script with the answer.

    This is the only post-action today and the default for
    :func:`request_user_input`. Pass the flag(s) the answer should land on; they
    are appended to the current invocation::

        await request_user_input(
            [select_one("Pick a country", [("us", "US"), ("eu", "EU")])],
            post_action=resume_script("--country"),
        )
        # → re-run: python main.py --country '{"responses": [...]}'

    For an explicit command, pass ``command=[...]``. ``cwd`` defaults to the
    current working directory. The platform appends the response JSON as the final
    argv token of ``command``.
    """
    cmd = list(command) if command is not None else resume_command_with(*flags)
    return {
        "type": POST_ACTION_RESUME_SCRIPT,
        "command": cmd,
        "cwd": cwd if cwd is not None else os.getcwd(),
    }


def run_workflow(
    workflow_name: str,
    code_directory_path: str,
    workflow_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the ``run_code_executor_workflow`` post-action — run the next phase of this workflow.

    The code-executor counterpart of :func:`resume_script`. A workflow cannot sit waiting for
    a human any more than a process can, so authored code asks and **halts**; once the user
    answers, the platform starts the phase named here as a fresh code-execution run, with the
    answer in its ``workflow_params`` under ``_user_input``::

        await request_user_input(
            [select_one("Category is Consulting — correct?", [("yes", "Yes"), ("no", "No")])],
            post_action=run_workflow(
                "ApplyCategoryDecision",
                code_directory_path="invoice_process/",       # the same directory this ran from
                workflow_params={"checkpoint": state_path},
            ),
        )
        return AWAITING_USER_INPUT        # ends this phase: halted, not finished

    Because the next phase is a fresh run, anything it needs from this one must be persisted
    before asking — through the filesystem or dataset actions — and pointed at from
    ``workflow_params``. Work *inside* a phase is checkpointed by Temporal and never repeats;
    only the phase boundary starts clean.

    ``code_directory_path`` is the directory this code was run from — pass the same one the
    tool was called with. Supplied rather than inferred: the executor receives the merged
    ``code_string``, never a path, so nothing in the run knows it. Writing it here keeps the
    post-action self-contained in its record, which is what lets it survive the run ending —
    the same reason ``resume_script`` stores ``argv`` and ``cwd`` rather than re-deriving them.
    """
    return {
        "type": POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
        "code_directory_path": code_directory_path,
        "workflow_name": workflow_name,
        "workflow_params": dict(workflow_params or {}),
    }
