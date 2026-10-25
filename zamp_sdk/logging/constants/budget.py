from datetime import timedelta

# Matches pantheon's EMIT_LOG_MAX_UPDATES, the most emits it accepts for one message.
DEFAULT_MAX_EMITS = 1200

# Emits are sent INLINE, so a slow agent would otherwise hold a pantheon API worker for the
# platform's default action timeout.
EMIT_TIMEOUT = timedelta(seconds=15)

EMIT_SENDING_STOPPED_ERROR = "log sending to the platform is stopped for this run"
