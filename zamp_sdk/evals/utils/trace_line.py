def line_id(name: str, key: str | None, n: int) -> str:
    return f"{name}{f':{key}' if key is not None else ''}#{n}"
