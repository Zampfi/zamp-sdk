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

# Post-action that starts the next phase of a code-executor workflow. Must stay in sync with
# pantheon's POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW.
POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW = "run_code_executor_workflow"

# What each post-action type must state to be actionable. A type belongs to exactly one
# runtime, so this doubles as "which post-action does that runtime accept". Adding a type is
# an entry here plus a builder in ``user_input/utils/resume`` — no code branches on the type.
POST_ACTION_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    POST_ACTION_RESUME_SCRIPT: ("command",),
    POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW: ("code_directory_path", "workflow_name"),
}

# workflow_params key the platform injects the answer under when it starts that phase. Must
# stay in sync with pantheon's USER_INPUT_WORKFLOW_PARAMS_KEY.
USER_INPUT_WORKFLOW_PARAMS_KEY = "_user_input"

# Key the host reads off ``workflow_impl``'s return value to tell a halted run from a
# finished one — no ambient state, just the output. Must stay in sync with the executor's
# AWAITING_USER_INPUT_KEY.
AWAITING_USER_INPUT_KEY = "_awaiting_user_input"

# What a phase returns after asking: ``return AWAITING_USER_INPUT``. Ready-made so the key is
# never typed by hand — a mistyped key is the one mistake in this flow that fails silently,
# reporting the run as finished while the question sits unanswered.
AWAITING_USER_INPUT = {AWAITING_USER_INPUT_KEY: True}
