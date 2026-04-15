"""
Workflow models for the Zamp SDK.
"""

from pydantic import BaseModel, Field


class CodeWorkflowCoreParams(BaseModel):
    """
    Core parameters for workflow execution.

    ``code_directory_path`` points to a directory of Python scripts in the org
    filesystem that the engine will load and execute.
    """

    code_directory_path: str = Field(
        ...,
        description="Path to a directory in the org filesystem containing Python scripts.",
    )
