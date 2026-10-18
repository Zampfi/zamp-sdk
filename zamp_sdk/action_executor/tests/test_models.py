from datetime import timedelta
from typing import Optional

import pytest
from pydantic import BaseModel, ValidationError

from zamp_sdk.action_executor.execution_mode import ExecutionMode
from zamp_sdk.action_executor.models import (
    DEFAULT_RETRY_BACKOFF_COEFFICIENT,
    DEFAULT_RETRY_INITIAL_INTERVAL,
    DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
    DEFAULT_RETRY_MAXIMUM_INTERVAL,
    ActionRequest,
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


class _Output(BaseModel):
    value: int


class _ForeignRetryPolicy(BaseModel):
    maximum_attempts: int = 3


def _request(**overrides) -> ActionRequest:
    return ActionRequest(**{"action_name": "a", "params": {}, **overrides})


class TestActionRequest:
    """``ActionExecutor.execute`` builds this first, so a bad argument fails before any route is chosen."""

    @pytest.mark.parametrize("timeout", [timedelta(0), timedelta(seconds=-1)])
    def test_non_positive_timeout_is_rejected(self, timeout):
        with pytest.raises(ValidationError, match="action_start_to_close_timeout must be positive"):
            _request(action_start_to_close_timeout=timeout)

    def test_positive_timeout_is_kept(self):
        assert _request(action_start_to_close_timeout=timedelta(seconds=5)).action_start_to_close_timeout == timedelta(
            seconds=5
        )

    def test_exact_mode_string_becomes_the_enum(self):
        """Dispatch compares modes by identity, so a matching string must not stay a string."""
        assert _request(execution_mode="INLINE").execution_mode is ExecutionMode.INLINE

    @pytest.mark.parametrize("mode", ["inline", "FOO"])
    def test_unknown_mode_is_rejected(self, mode):
        with pytest.raises(ValidationError):
            _request(execution_mode=mode)

    @pytest.mark.parametrize("params", [{1: "x"}, None, ["x"]])
    def test_params_must_be_a_string_keyed_dict(self, params):
        with pytest.raises(ValidationError):
            _request(params=params)

    def test_retry_policy_accepts_the_model_or_a_complete_dict(self):
        policy = RetryPolicy.default()
        assert _request(action_retry_policy=policy).action_retry_policy == policy
        assert _request(action_retry_policy=policy.model_dump()).action_retry_policy == policy

    @pytest.mark.parametrize("policy", [_ForeignRetryPolicy(), {"maximum_attempts": 2}])
    def test_retry_policy_rejects_another_class_or_a_partial_dict(self, policy):
        with pytest.raises(ValidationError):
            _request(action_retry_policy=policy)

    def test_return_type_accepts_a_class(self):
        assert _request(return_type=_Output).return_type is _Output

    @pytest.mark.parametrize("hint", [list[_Output], Optional[_Output], _Output(value=1)])
    def test_return_type_rejects_what_is_not_a_class(self, hint):
        with pytest.raises(ValidationError):
            _request(return_type=hint)

    def test_is_frozen(self):
        with pytest.raises(ValidationError):
            _request().action_name = "b"
