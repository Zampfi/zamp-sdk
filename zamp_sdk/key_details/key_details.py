"""Record dataset key-details (the values shown on a task in the task list, and
their filters) from a sandboxed script — the same recording the agent does via
its tools on the direct path.

    from zamp_sdk import (
        get_dataset_key_details,
        upsert_dataset_key_details,
        record_task_key_detail_rows,
    )

    cfg = await get_dataset_key_details("invoices")
    if not cfg["registered"]:
        await upsert_dataset_key_details(
            "invoices",
            columns=[{"label": "Invoice #", "column": "invoice_number"},
                     {"label": "Vendor", "column": "vendor"}],
        )
    await record_task_key_detail_rows("invoices", row_ids=[101, 102, 103])
"""

import os
from typing import Any, List, Optional

import structlog

from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.context import ENV_CHANNEL_ID, ENV_CHANNEL_TYPE
from zamp_sdk.key_details.constants import (
    GET_DATASET_KEY_DETAILS_ACTION,
    RECONCILE_DATASET_CHANGE_ACTION,
    UPDATE_TASK_KEY_DETAIL_ROWS_ACTION,
    UPSERT_DATASET_KEY_DETAILS_ACTION,
)
from zamp_sdk.key_details.constants.actions import TASK_CHANNEL_TYPE

logger = structlog.get_logger(__name__)


def _resolve_task_id() -> Optional[str]:
    """The running task's id from the channel context, or None outside a task.

    ZAMP_CHANNEL_ID equals the task id only when the channel is a task; in other
    contexts it is a conversation/user id, so callers no-op instead of sending it.
    """
    if os.environ.get(ENV_CHANNEL_TYPE) != TASK_CHANNEL_TYPE:
        return None
    return os.environ.get(ENV_CHANNEL_ID) or None


async def record_task_key_detail_rows(
    table_name: str,
    row_ids: List[int],
) -> dict:
    """Record the dataset rows this task touched so they surface as key-details.

    Additive across calls; duplicates dedupe. Returns the action result, or
    ``{"recorded": False}`` outside a task context (e.g. a conversation turn).
    """
    task_id = _resolve_task_id()
    if not task_id:
        logger.info(
            "record_task_key_detail_rows: no task channel context; skipping",
            table_name=table_name,
        )
        return {"recorded": False}

    params: dict[str, Any] = {
        "task_id": task_id,
        "rows": [{"table": table_name, "row_ids": list(row_ids)}],
    }
    return await ActionExecutor.execute(
        UPDATE_TASK_KEY_DETAIL_ROWS_ACTION,
        params,
        summary="Record dataset key-detail rows for the current task",
    )


async def get_dataset_key_details(table_name: str) -> dict:
    """Read the saved key-detail column config for a dataset table.

    ``registered`` is ``False`` when nothing has been saved for the table yet.
    """
    return await ActionExecutor.execute(
        GET_DATASET_KEY_DETAILS_ACTION,
        {"table_name": table_name},
        summary="Read a dataset's key-detail column config",
    )


async def upsert_dataset_key_details(
    table_name: str,
    columns: List[dict],
) -> dict:
    """Wholesale-replace a dataset table's key-detail column config.

    ``columns`` is the COMPLETE desired set of ``{"label", "column"}`` entries,
    not a delta — read the current set with :func:`get_dataset_key_details` first
    and re-send anything you mean to keep.
    """
    return await ActionExecutor.execute(
        UPSERT_DATASET_KEY_DETAILS_ACTION,
        {"table_name": table_name, "columns": list(columns)},
        summary="Register a dataset's key-detail columns",
    )


async def reconcile_dataset_change(
    action: str,
    old_table_name: str,
    new_table_name: Optional[str] = None,
) -> dict:
    """Repoint the key-detail bridge after a dataset table rename or drop.

    Call after the DDL runs. ``action`` is ``"RENAME"`` (with ``new_table_name``)
    or ``"DROP"`` (omit ``new_table_name``).
    """
    params: dict[str, Any] = {
        "action": action,
        "old_table_name": old_table_name,
    }
    if new_table_name is not None:
        params["new_table_name"] = new_table_name
    return await ActionExecutor.execute(
        RECONCILE_DATASET_CHANGE_ACTION,
        params,
        summary="Reconcile the key-detail bridge after a dataset table change",
    )
