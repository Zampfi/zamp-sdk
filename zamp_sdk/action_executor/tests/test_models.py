from datetime import timedelta

from zamp_sdk.action_executor.models import (
    DEFAULT_RETRY_BACKOFF_COEFFICIENT,
    DEFAULT_RETRY_INITIAL_INTERVAL,
    DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
    DEFAULT_RETRY_MAXIMUM_INTERVAL,
    RetryPolicy,
)


class TestRetryPolicy:
    def test_fields(self):
        rp = RetryPolicy(
            initial_interval=timedelta(seconds=10),
            maximum_attempts=5,
            maximum_interval=timedelta(minutes=1),
            backoff_coefficient=2.0,
        )
        assert rp.initial_interval == timedelta(seconds=10)
        assert rp.maximum_attempts == 5
        assert rp.maximum_interval == timedelta(minutes=1)
        assert rp.backoff_coefficient == 2.0

    def test_default_values(self):
        rp = RetryPolicy.default()
        assert rp.initial_interval == DEFAULT_RETRY_INITIAL_INTERVAL
        assert rp.maximum_attempts == DEFAULT_RETRY_MAXIMUM_ATTEMPTS
        assert rp.maximum_interval == DEFAULT_RETRY_MAXIMUM_INTERVAL
        assert rp.backoff_coefficient == DEFAULT_RETRY_BACKOFF_COEFFICIENT

    def test_serialization(self):
        rp = RetryPolicy.default()
        data = rp.model_dump(mode="json")
        assert isinstance(data, dict)
        assert "initial_interval" in data
        assert "maximum_attempts" in data
        assert "maximum_interval" in data
        assert "backoff_coefficient" in data
        assert data["maximum_attempts"] == DEFAULT_RETRY_MAXIMUM_ATTEMPTS
        assert data["backoff_coefficient"] == DEFAULT_RETRY_BACKOFF_COEFFICIENT
