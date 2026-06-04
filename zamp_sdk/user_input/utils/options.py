from __future__ import annotations

from zamp_sdk.user_input.models import InputOption


def build_options(options: list) -> list[dict]:
    """Normalize question options to the dict shape the platform expects.

    Accepts :class:`InputOption`, raw dicts, or ``(id, label)`` tuples/lists.
    """
    out: list[dict] = []
    for opt in options:
        if isinstance(opt, InputOption):
            out.append(opt.model_dump(exclude_none=True))
        elif isinstance(opt, dict):
            out.append(opt)
        elif isinstance(opt, (tuple, list)) and len(opt) >= 2:
            out.append({"id": opt[0], "label": opt[1]})
        else:
            raise ValueError(f"Unsupported option: {opt!r} (use (id, label) or InputOption)")
    return out
