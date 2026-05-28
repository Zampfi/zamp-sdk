"""Content block models — mirrored from
``pantheon_v2/platform/utils/common/models.py``.

The platform represents every renderable piece of agent output (text,
thinking, tool use, tool result, …) as members of one discriminated union:
``ContentBlock``. To avoid having a *parallel* set of "log block" models in
the SDK, we replicate the relevant subset here and use the **same** shape
end-to-end: a script emits ``ContentBlock`` instances and the platform appends
them to the running agent's message as-is.

The three block kinds replicated here are the ones a sandboxed script can
meaningfully produce — text, tool_use, tool_result. The remaining platform-side
members (markdown, thinking, task, agent, trigger, …) are server-generated and
intentionally not exposed in the SDK.

If pantheon adds fields to these models, mirror them here.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class ContentBlockType(str, Enum):
    """Subset of pantheon's ContentBlockType — the kinds emit_log accepts."""

    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class ContentBlockBase(BaseModel):
    """Base for all content block types. Do not instantiate directly."""

    index: int = Field(
        default=0,
        description=(
            "Placeholder index — the platform's ContentBlockManager reassigns "
            "the real index when appending to the live agent message."
        ),
    )
    is_complete: bool = Field(default=True, description="Whether block is complete")
    start_timestamp: Optional[str] = Field(default=None, description="Block start time")
    stop_timestamp: Optional[str] = Field(default=None, description="Block stop time")
    parent_block_id: Optional[str] = Field(
        default=None,
        description=(
            "``id`` of the parent block this block belongs to (today, always a "
            "tool_use block). emit_log auto-stamps the running sandbox tool's id, "
            "so the FE groups emitted blocks under the correct tool even when "
            "multiple parallel tool calls are active. Leave unset and emit_log will "
            "fill it in from ZAMP_TOOL_CALL_ID."
        ),
    )


class TextContentBlock(ContentBlockBase):
    type: Literal[ContentBlockType.TEXT] = ContentBlockType.TEXT
    content: Optional[str] = Field(default=None, description="Text content")


class ToolUseContentBlock(ContentBlockBase):
    """Half one of a tool call — pair with a :class:`ToolResultContentBlock`
    that shares the same ``id``."""

    type: Literal[ContentBlockType.TOOL_USE] = ContentBlockType.TOOL_USE
    id: Optional[str] = Field(default=None, description="Tool call id (pairing key)")
    name: Optional[str] = Field(default=None, description="Tool name")
    display_name: Optional[str] = Field(
        default=None, description="Static human-readable display name"
    )
    display_title: Optional[str] = Field(
        default=None,
        description=(
            "Short summary the FE prefers over name/display_name as the header "
            "(e.g. 'Fetching invoice INV-2024-001')."
        ),
    )
    icon: Optional[str] = Field(default=None, description="Tool integration icon URL")
    input_json: Optional[str] = Field(
        default=None, description="Tool input as JSON string"
    )
    tool_call: Optional[Any] = Field(
        default=None, description="Full tool call object (deprecated)"
    )


class ToolResultContentBlock(ContentBlockBase):
    """Half two of a tool call — share ``id`` with the matching tool_use."""

    type: Literal[ContentBlockType.TOOL_RESULT] = ContentBlockType.TOOL_RESULT
    id: Optional[str] = Field(
        default=None, description="Tool call id (matches the paired tool_use)"
    )
    name: Optional[str] = Field(default=None, description="Tool name")
    content: Optional[str] = Field(default=None, description="Tool result content")


# Discriminated union — emit_log accepts a list of these.
ContentBlock = Annotated[
    Union[
        TextContentBlock,
        ToolUseContentBlock,
        ToolResultContentBlock,
    ],
    Field(discriminator="type"),
]
