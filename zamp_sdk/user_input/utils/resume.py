from __future__ import annotations

import os
import sys
from typing import Any, Optional

from zamp_sdk.user_input.constants import POST_ACTION_RESUME_SCRIPT


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
