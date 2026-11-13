from enum import StrEnum


class ActionStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    TERMINATED = "TERMINATED"
    TIMED_OUT = "TIMED_OUT"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


SUCCESS_STATUSES = frozenset({ActionStatus.COMPLETED})
TERMINAL_FAILURE_STATUSES = frozenset(
    {
        ActionStatus.FAILED,
        ActionStatus.CANCELED,
        ActionStatus.TERMINATED,
        ActionStatus.TIMED_OUT,
    }
)
IN_PROGRESS_STATUSES = frozenset({ActionStatus.RUNNING})
# Refused until a human approves the call: not a failure, and not a state to keep polling.
APPROVAL_REQUIRED_STATUSES = frozenset({ActionStatus.APPROVAL_REQUIRED})
