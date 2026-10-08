"""The runtime hosting this process, and how the SDK reads it.

One fact with two consequences: it decides how actions dispatch (in-process through an
ActionsHub, or over HTTP to the Zamp API) and where the channel context comes from (bound
in-process by the running workflow, or injected as ``ZAMP_*`` environment variables).

Declared once by the host process, never per call.
"""

from __future__ import annotations

import os
from enum import StrEnum

from zamp_sdk.context.env import ENV_EXECUTION_HOST


class ExecutionHost(StrEnum):
    """The runtime hosting this process.

    ``API`` — no local orchestrator. Actions are POSTed to the Zamp API and polled, and the
    channel context is read from the environment the runtime injected. The default, and the
    only mode available to an external caller.

    ``ACTIONS_HUB`` — an ActionsHub is present in-process (zamp-executor). Actions dispatch
    through it, and the channel context is the one the running workflow bound.
    """

    API = "api"
    ACTIONS_HUB = "actions_hub"


def current_execution_host() -> ExecutionHost:
    """Resolve the host from the environment, defaulting to ``API``.

    Defaulting to the API means an SDK used outside Zamp's own runtimes needs no
    configuration. An unrecognised value raises rather than falling back, because a typo
    would otherwise silently change both the transport and the context source.
    """
    raw = os.environ.get(ENV_EXECUTION_HOST)
    if raw is None or not raw.strip():
        return ExecutionHost.API
    try:
        return ExecutionHost(raw.strip().lower())
    except ValueError:
        valid = ", ".join(sorted(host.value for host in ExecutionHost))
        raise ValueError(
            f"{ENV_EXECUTION_HOST}={raw!r} is not a known execution host (expected one of: {valid})"
        ) from None
