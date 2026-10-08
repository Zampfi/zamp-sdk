# The one platform action every decorated call and every trace read goes through.
EVAL_DOOR_ACTION = "eval_door"

# <system>.<what>, written once on the decorated function: erp.order_detail, ask.decision.
CALL_NAME_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"

# The value of the parameter the decorator names as key; '#' is kept for the call id.
KEY_VALUE_PATTERN = r"^[^#\s]+$"

# module.Class of an error a fixture raises, imported and built as type(message).
ERROR_TYPE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$"
