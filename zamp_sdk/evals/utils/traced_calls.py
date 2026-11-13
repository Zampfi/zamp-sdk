import inspect

from zamp_sdk.decorated_calls.utils import arguments_without_credentials, bind_arguments, new_call_id
from zamp_sdk.evals.models import TracedCallInput
from zamp_sdk.evals.utils.arguments import key_from_arguments


def build_traced_call_input(
    name: str,
    key_argument: str | None,
    signature: inspect.Signature,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    parent: str,
) -> TracedCallInput:
    arguments = bind_arguments(signature, args, kwargs)

    return TracedCallInput(
        name=name,
        key=key_from_arguments(arguments, key_argument),
        invocation_id=new_call_id(),
        parent=parent,
        args=arguments_without_credentials(arguments),
    )
