# Request headers the platform reads to run an action inside a branch, keyed by the
# current_branch_context() field they carry.
BRANCH_HEADERS = {
    "branch_id": "X-BRANCH-ID",
    "db_branch_mode": "X-DB-BRANCH-MODE",
    "environment": "X-ENVIRONMENT",
}

# Request headers the platform reads to run an action inside an eval trial and a mock case; they carry
# current_eval_trial_id() and current_mock_case_id().
EVAL_TRIAL_ID_HEADER = "X-EVAL-TRIAL-ID"
MOCK_CASE_ID_HEADER = "X-MOCK-CASE-ID"
