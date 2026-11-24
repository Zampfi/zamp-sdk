from zamp_sdk.db.utils.errors import AgentDbError

# These pull in sqlalchemy; each is loaded on first use, not when zamp_sdk.db.utils is imported.
_LAZY = {
    "compile_statement": "zamp_sdk.db.utils.compile",
    "build_table": "zamp_sdk.db.utils.table_builder",
    "Transaction": "zamp_sdk.db.utils.transaction",
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentDbError",
    "Transaction",
    "build_table",
    "compile_statement",
]
