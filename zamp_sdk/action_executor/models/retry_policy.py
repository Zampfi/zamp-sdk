from datetime import timedelta

from pydantic import BaseModel

DEFAULT_RETRY_INITIAL_INTERVAL = timedelta(seconds=30)
DEFAULT_RETRY_MAXIMUM_ATTEMPTS = 11
DEFAULT_RETRY_MAXIMUM_INTERVAL = timedelta(minutes=15)
DEFAULT_RETRY_BACKOFF_COEFFICIENT = 1.5


class RetryPolicy(BaseModel):
    initial_interval: timedelta
    maximum_attempts: int
    maximum_interval: timedelta
    backoff_coefficient: float

    @staticmethod
    def default() -> "RetryPolicy":
        return RetryPolicy(
            initial_interval=DEFAULT_RETRY_INITIAL_INTERVAL,
            maximum_attempts=DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
            maximum_interval=DEFAULT_RETRY_MAXIMUM_INTERVAL,
            backoff_coefficient=DEFAULT_RETRY_BACKOFF_COEFFICIENT,
        )
