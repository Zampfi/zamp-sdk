from __future__ import annotations

import sys


def resume_command_with(*flags: str) -> list[str]:
    """Build a resume command: the current invocation plus the flag(s) the answer
    should be appended after.

    The platform re-runs ``<resume_command> '<answer-json>'`` once the user
    answers — it simply appends the response JSON as the final argv token. So end
    the command with the flag you want that JSON to land on::

        await request_user_input(
            [select_one("Pick a country", [("us", "US"), ("eu", "EU")])],
            resume_command=resume_command_with("--country"),
        )
        # → re-run: python main.py --country '{"responses": [...]}'

    For **sequential** HITLs this also threads prior answers through: on a re-run
    ``sys.argv`` already carries the earlier ``--flag '<json>'`` pairs, so passing
    a fresh flag here keeps every previous answer on the command line — no
    checkpoint file needed.

    ``sys.argv`` omits the interpreter (``["main.py", ...]``); we prepend
    ``sys.executable`` so the re-run is a valid ``python main.py ...`` invocation.
    """
    return [sys.executable, *sys.argv, *flags]


def default_resume_command() -> list[str]:
    """The current invocation, ready to re-run (interpreter prepended).

    Equivalent to :func:`resume_command_with` with no extra flags — the answer
    JSON is appended as a trailing positional argument.
    """
    return resume_command_with()
