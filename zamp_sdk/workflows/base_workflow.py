"""Base class for workflows executed by the universal workflow engine."""

from abc import ABC, abstractmethod
from typing import Any, Dict

from zamp_sdk.workflows.models import CodeWorkflowCoreParams


class BaseWorkflow(ABC):
    """
    Base class for workflows executed by the universal workflow engine.

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
