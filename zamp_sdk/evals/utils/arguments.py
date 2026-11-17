import inspect


def accepts_argument(signature: inspect.Signature, argument_name: str) -> bool:
    return any(
        parameter.name == argument_name or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def key_from_arguments(arguments: dict[str, object], key_argument: str | None) -> str | None:
    value = None if key_argument is None else arguments.get(key_argument)

    return None if value is None else str(value)
