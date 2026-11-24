"""Agent-managed database access for scripts.

Write ordinary SQLAlchemy; the bridge compiles it and ships it to the platform. No
DSN, no connection, no credential ever reaches the script.

    from zamp_sdk.db import datasets

    invoices = await datasets.table("invoices")
    rows = await datasets.execute(select(invoices).where(invoices.c.status == "open"))
"""

from zamp_sdk.db.utils.errors import AgentDbError


def __getattr__(name: str):
    # datasets pulls in sqlalchemy; it is loaded on first use, not when zamp_sdk.db is imported.
    if name == "datasets":
        import importlib

        return importlib.import_module("zamp_sdk.db.datasets")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AgentDbError", "datasets"]
