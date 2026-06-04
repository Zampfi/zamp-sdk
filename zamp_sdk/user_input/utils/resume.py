from __future__ import annotations

import sys

from zamp_sdk.user_input.constants import HITL_RESPONSE_FLAG


def strip_hitl_flag(argv: list[str]) -> list[str]:
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


def default_resume_command() -> list[str]:
    """The argv to re-run, with the interpreter prepended and stale --hitl removed.

    ``sys.argv`` omits the interpreter (``["main.py", ...]``), so re-running it
    verbatim would try to exec ``main.py`` as a program. Prepend
    ``sys.executable`` → ``["/usr/bin/python", "main.py", ...]``.
    """
    return [sys.executable, *strip_hitl_flag(sys.argv)]
