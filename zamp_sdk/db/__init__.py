"""Agent-managed database access for scripts.

Write ordinary SQLAlchemy; the bridge compiles it and ships it to the platform. No
DSN, no connection, no credential ever reaches the script.

    from zamp_sdk.db import datasets

    invoices = await datasets.table("invoices")
    rows = await datasets.execute(select(invoices).where(invoices.c.status == "open"))
"""

from zamp_sdk.db import datasets
from zamp_sdk.db.utils import AgentDbError

__all__ = ["AgentDbError", "datasets"]
