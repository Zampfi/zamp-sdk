from zamp_sdk.version import __version__

# Request headers the platform reads to run an action inside a branch, keyed by the
# current_branch_context() field they carry.
BRANCH_HEADERS = {
    "branch_id": "X-BRANCH-ID",
    "db_branch_mode": "X-DB-BRANCH-MODE",
    "environment": "X-ENVIRONMENT",
}

# Sent on every request, so the platform can tell which SDK version is calling.
USER_AGENT_HEADER = "User-Agent"
USER_AGENT = f"zamp-sdk/{__version__}"

# Sent with a 429: when a refused request may succeed. The platform sends whole seconds; a
# proxy in front of it may send an HTTP-date instead.
RETRY_AFTER_HEADER = "Retry-After"
