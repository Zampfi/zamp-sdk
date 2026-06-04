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
