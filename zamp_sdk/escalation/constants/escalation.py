# Constants for escalate(): a stuck phase or script hands its blocker to the agent that ran it.

# Key a phase's return value carries its escalation under: ``return escalate(...)``. The executor
# passes any return value without AWAITING_USER_INPUT_KEY through as the run's result, so the
# escalation reaches the platform unchanged. Must stay in sync with pantheon's ESCALATION_KEY.
ESCALATION_KEY = "_zamp_escalation"

# workflow_params key the platform puts the answers under when it starts the next phase. Must
# stay in sync with pantheon's ESCALATION_WORKFLOW_PARAMS_KEY.
ESCALATION_WORKFLOW_PARAMS_KEY = "_escalation"

# Printed to stdout by a sandbox script just before it exits, followed by the escalation as
# JSON. The platform matches this exact prefix, as it does SDK_USER_INPUT_MARKER.
SDK_ESCALATION_MARKER = "__ZAMP_SDK_ESCALATION__"

# Who answered a question; one per answer in the next run's EscalationAnswer.
ANSWERED_BY_AGENT = "agent"
ANSWERED_BY_HUMAN = "human"
ANSWERED_BY_PARENT_AGENT = "parent_agent"

# Size caps: everything in an escalation reaches an LLM's context and, when asked, a person's
# card, so it stays short. Details hold what the code saw; files carry anything longer.
MAX_SUMMARY_CHARS = 300
MAX_DETAILS_BYTES = 16 * 1024
MAX_FILES = 20
MAX_QUESTIONS = 10

# The question types an escalation can ask; the same shapes the request builders produce.
QUESTION_INPUT_TYPES = ("text", "select_one", "multiple_choice")
OPTION_INPUT_TYPES = ("select_one", "multiple_choice")
