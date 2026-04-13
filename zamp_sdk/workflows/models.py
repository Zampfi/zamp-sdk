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

from pydantic import BaseModel, Field, model_validator


class CodeWorkflowCoreParams(BaseModel):
    """
    Core parameters for V2 workflow execution supporting both S3 and filesystem sources.

    Either ``zip_file_name`` (for S3) or ``code_file_path`` (for filesystem) must be
    provided. When both are set, ``code_file_path`` takes precedence.
    """

    zip_file_name: Optional[str] = Field(
        default=None,
        description="Name of the zip file in S3. Required when using S3 source.",
    )
    code_file_path: Optional[str] = Field(
        default=None,
        description=(
            "Path to a Python script in the org filesystem. "
            "When provided, code is read from the filesystem instead of S3 zip."
        ),
    )

    @model_validator(mode="after")
    def validate_source(self) -> "CodeWorkflowCoreParams":
        if not self.zip_file_name and not self.code_file_path:
            raise ValueError("Either zip_file_name or code_file_path must be provided")
        return self


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

    @model_validator(mode="after")
    def validate_code_source(self) -> "UniversalWorkflowV2Input":
        if not self.code_string and not self.core_params.code_file_path:
            raise ValueError(
                "Either code_string or core_params.code_file_path must be provided"
            )
        return self


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
