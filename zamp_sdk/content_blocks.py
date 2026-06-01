"""Content block models accepted by :func:`zamp_sdk.emit_log`.

A script emits one of three inner block types — text, tool_use, tool_result —
and :func:`emit_log` wraps each one in a :class:`ToolEmitLogBlock` that carries
the running tool's id, so the platform can group the emitted blocks under the
parent ``sandbox_user_exec`` call on the agent's live message.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class ContentBlockType(str, Enum):
    """Kinds of content block emit_log accepts."""

    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    TOOL_EMIT_LOG = "tool_emit_log"


class ContentBlockBase(BaseModel):
    """Base for all content block types. Do not instantiate directly."""

    index: int = Field(
        default=0,
        description="Server-assigned position in the message. Leave at the default.",
    )
    is_complete: bool = Field(default=True, description="Whether block is complete")
    start_timestamp: Optional[str] = Field(default=None, description="Block start time")
    stop_timestamp: Optional[str] = Field(default=None, description="Block stop time")


class TextContentBlock(ContentBlockBase):
    type: Literal[ContentBlockType.TEXT] = ContentBlockType.TEXT
    content: Optional[str] = Field(default=None, description="Text content")


class ToolUseContentBlock(ContentBlockBase):
    """Half one of a tool call — pair with a :class:`ToolResultContentBlock`
    that shares the same ``id``."""

    type: Literal[ContentBlockType.TOOL_USE] = ContentBlockType.TOOL_USE
    id: Optional[str] = Field(default=None, description="Tool call id (pairing key)")
    name: Optional[str] = Field(default=None, description="Tool name")
    display_name: Optional[str] = Field(default=None, description="Static human-readable display name")
    display_title: Optional[str] = Field(
        default=None,
        description=(
            "Short summary shown as the block header (e.g. 'Fetching invoice INV-2024-001'). Preferred over name."
        ),
    )
    input_json: Optional[str] = Field(default=None, description="Tool input as JSON string")
    tool_call: Optional[Any] = Field(default=None, description="Full tool call object (deprecated)")


class ToolResultContentBlock(ContentBlockBase):
    """Half two of a tool call — share ``id`` with the matching tool_use."""

    type: Literal[ContentBlockType.TOOL_RESULT] = ContentBlockType.TOOL_RESULT
    id: Optional[str] = Field(default=None, description="Tool call id (matches the paired tool_use)")
    name: Optional[str] = Field(default=None, description="Tool name")
    content: Optional[str] = Field(default=None, description="Tool result content")


InnerContentBlock = Annotated[
    Union[TextContentBlock, ToolUseContentBlock, ToolResultContentBlock],
    Field(discriminator="type"),
]


class ToolEmitLogBlock(ContentBlockBase):
    """Wrapper that ties an emitted log block to its parent ``sandbox_user_exec``
    tool call. Streamed flat in the agent's message; the FE groups all wrappers
    sharing the same ``tool_id`` under that tool's Activity section.
    """

    type: Literal[ContentBlockType.TOOL_EMIT_LOG] = ContentBlockType.TOOL_EMIT_LOG
    tool_id: str = Field(
        description="``id`` of the parent sandbox tool call this log belongs to."
    )
    content: InnerContentBlock = Field(
        description="The actual log payload — text, tool_use, or tool_result."
    )


ContentBlock = Annotated[
    Union[
        TextContentBlock,
        ToolUseContentBlock,
        ToolResultContentBlock,
        ToolEmitLogBlock,
    ],
    Field(discriminator="type"),
]
