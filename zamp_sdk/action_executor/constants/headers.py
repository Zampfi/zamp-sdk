# Request headers the platform reads to run an action inside a branch, keyed by the
# current_branch_context() field they carry.
BRANCH_HEADERS = {
    "branch_id": "X-BRANCH-ID",
    "db_branch_mode": "X-DB-BRANCH-MODE",
    "environment": "X-ENVIRONMENT",
}

EVAL_TRIAL_HEADER = "X-EVAL-TRIAL-ID"
