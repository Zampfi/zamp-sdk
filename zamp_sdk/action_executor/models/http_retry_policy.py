from pydantic import BaseModel, Field

from zamp_sdk.action_executor.constants import (
    DEFAULT_5XX_BACKOFF_COEFFICIENT,
    DEFAULT_5XX_INITIAL_INTERVAL_SECONDS,
    DEFAULT_5XX_MAX_ATTEMPTS,
    DEFAULT_5XX_MAX_INTERVAL_SECONDS,
)


class Http5xxRetryPolicy(BaseModel):
    """Retry policy for transient 5xx responses on the action-create POST.

    This is a client-side transport concern, distinct from ``RetryPolicy`` (the
    server-side action retry policy forwarded in the request body).
    """

    max_attempts: int = Field(ge=1)
    initial_interval_seconds: float = Field(gt=0)
    max_interval_seconds: float = Field(gt=0)
    backoff_coefficient: float = Field(ge=1)

    @staticmethod
    def default() -> "Http5xxRetryPolicy":
        return Http5xxRetryPolicy(
            max_attempts=DEFAULT_5XX_MAX_ATTEMPTS,
            initial_interval_seconds=DEFAULT_5XX_INITIAL_INTERVAL_SECONDS,
            max_interval_seconds=DEFAULT_5XX_MAX_INTERVAL_SECONDS,
            backoff_coefficient=DEFAULT_5XX_BACKOFF_COEFFICIENT,
        )

    def next_interval(self, current: float) -> float:
        """The next backoff interval, capped at ``max_interval_seconds``."""
        return min(current * self.backoff_coefficient, self.max_interval_seconds)
