# Constants for the human-in-the-loop (HITL) pause-and-resume protocol used by
# sandboxed scripts.

# Printed verbatim to stdout immediately before the script exits. The platform
# matches this exact prefix to distinguish a script that paused for human input
# from one that crashed, so the run ends in a "needs input" state rather than a
# failure state.
SDK_USER_INPUT_MARKER = "__ZAMP_SDK_USER_INPUT__"

# Exit code used when pausing for human input. A secondary signal only: the
# marker line above is authoritative regardless of how the host interprets the
# exit code.
SDK_USER_INPUT_EXIT_CODE = 42

# Post-action type sent with the request: what should happen once the user
# answers. Only "resume_script" (re-run the script with the answer) exists today;
# the platform models this as a discriminated structure so other post-actions can
# be added later.
POST_ACTION_RESUME_SCRIPT = "resume_script"
