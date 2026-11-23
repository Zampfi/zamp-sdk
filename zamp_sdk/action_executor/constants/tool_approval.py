"""The protocol for halting code whose tool call needs a human's approval."""

# Printed verbatim to stdout, followed by a JSON payload, immediately before a sandbox script
# exits. The platform matches this prefix to tell a script waiting on an approval from one that
# crashed. Must stay in sync with pantheon.
SDK_TOOL_APPROVAL_MARKER = "__ZAMP_SDK_TOOL_APPROVAL__"

# Exit code of a script halted for approval. The platform uses both signals: the marker names the
# approval (policy_result_id), exit 43 shows the script really stopped. A marker with another exit
# code means the stop was caught; exit 43 without a marker makes the platform look up the pending
# row. Must stay in sync with pantheon.
SDK_TOOL_APPROVAL_EXIT_CODE = 43
