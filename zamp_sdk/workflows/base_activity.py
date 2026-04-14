"""Base class for activities executed by the workflow engine."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseActivity(ABC):
    """
    Base class for activities executed by the workflow engine.

    Subclasses must implement ``activity_impl``. The method can be async or sync.
    """

    @abstractmethod
    def activity_impl(self, activity_params: Dict[str, Any]) -> Any:
        """Main activity implementation function."""
        ...
