"""Content block models accepted by :func:`zamp_sdk.emit_log`.

Each block represents one piece of agent output: a text update, a tool call,
or a tool result. They are appended to the running agent's live message in
the order they're emitted.
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


class ContentBlockBase(BaseModel):
    """Base for all content block types. Do not instantiate directly."""

    index: int = Field(
        default=0,
        description="Server-assigned position in the message. Leave at the default.",
    )
    is_complete: bool = Field(default=True, description="Whether block is complete")
    start_timestamp: Optional[str] = Field(default=None, description="Block start time")
    stop_timestamp: Optional[str] = Field(default=None, description="Block stop time")
    parent_block_id: Optional[str] = Field(
        default=None,
        description=(
            "``id`` of the parent block this block belongs to. Leave unset and "
            "emit_log will fill it in from the running tool's id."
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
            "Short summary shown as the block header "
            "(e.g. 'Fetching invoice INV-2024-001'). Preferred over name."
        ),
    )
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


ContentBlock = Annotated[
    Union[
        TextContentBlock,
        ToolUseContentBlock,
        ToolResultContentBlock,
    ],
    Field(discriminator="type"),
]
