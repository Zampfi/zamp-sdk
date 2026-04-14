"""
Workflow type stubs exposed to customers.

These models mirror the shapes accepted by Pantheon's V2 universal workflow
engine (`UniversalWorkflowV2`) and dynamic-activity workflow
(`ExecuteDynamicActivityWorkflow`). Customers subclass `BaseWorkflow` to
implement workflow logic; the SDK ships these types so customer code does not
need to depend on the Pantheon repository.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CodeWorkflowCoreParams(BaseModel):
    """
    Core parameters for workflow execution.

    ``code_file_path`` points to a Python script (or directory of scripts) in
    the org filesystem that the engine will load and execute.
    """

    code_file_path: str = Field(
        ...,
        description="Path to a Python script or directory in the org filesystem.",
    )


class BaseWorkflow(ABC):
    """
    Base class for customer-authored workflows executed by Pantheon's V2 universal
    workflow engine.

    Subclasses must implement ``workflow_impl``. The signature is enforced so that
    workflow code can be discovered and invoked by name at runtime.
    """

    @abstractmethod
    async def workflow_impl(
        self,
        workflow_params: Dict[str, Any],
        core_params: CodeWorkflowCoreParams,
    ) -> Any:
        """Main workflow implementation function."""
        ...


class UniversalWorkflowV2Input(BaseModel):
    """Input schema for the ``UniversalWorkflowV2`` action."""

    code_string: Optional[str] = Field(
        default=None,
        description=(
            "Python code to execute. Required unless core_params.code_file_path is set."
        ),
    )
    imports_list: Optional[List[str]] = None
    workflow_params: Dict[str, Any]
    core_params: CodeWorkflowCoreParams
    workflow_name: str

    # code_file_path is now required on CodeWorkflowCoreParams, so the engine
    # always has a filesystem source. code_string is optional (pre-fetched code
    # that skips the filesystem read when provided).


class ExecuteDynamicActivityWorkflowInput(BaseModel):
    """Input schema for the ``ExecuteDynamicActivityWorkflow`` action."""

    activity_name: str = Field(..., description="Name of the activity class to execute")
    core_params: CodeWorkflowCoreParams = Field(
        ...,
        description="Core parameters; code_file_path provides the directory for code fetch",
    )
    kwargs: Dict[str, Any] = Field(
        default_factory=dict, description="Keyword arguments to pass to the activity"
    )
    timeout_seconds: int = Field(
        default=30,
        description="Maximum execution time allowed for the activity in seconds",
    )


class ExecuteDynamicActivityWorkflowOutput(BaseModel):
    """Output schema for the ``ExecuteDynamicActivityWorkflow`` action."""

    result: Optional[Dict[str, Any]] = Field(
        None, description="Result of the activity execution if successful"
    )
    execution_time: float = Field(
        ..., description="Time taken for execution in seconds"
    )
