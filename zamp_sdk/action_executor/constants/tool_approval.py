"""The protocol for halting code whose tool call needs a human's approval."""

# Printed verbatim to stdout, followed by a JSON payload, immediately before a sandbox script
# exits. The platform matches this prefix to tell a script waiting on an approval from one that
# crashed. Must stay in sync with pantheon.
SDK_TOOL_APPROVAL_MARKER = "__ZAMP_SDK_TOOL_APPROVAL__"

# Exit code of a script halted for approval. A secondary signal: the marker is authoritative.
# Must stay in sync with pantheon.
SDK_TOOL_APPROVAL_EXIT_CODE = 43
