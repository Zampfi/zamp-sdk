import pytest

from zamp_sdk import evals
from zamp_sdk.mocks import mockable


def pages():
    yield 1


async def stream():
    yield 1


class TestDecorating:
    @pytest.mark.parametrize("decorator", [mockable, evals.observe])
    @pytest.mark.parametrize("generator", [pages, stream])
    def test_a_generator_is_refused(self, decorator, generator):
        with pytest.raises(TypeError, match=f"^calls.pages: {generator.__qualname__} is a generator"):
            decorator("calls.pages")(generator)

    def test_a_key_argument_that_is_not_a_parameter_is_refused(self):
        def fetch(order_id: str): ...

        with pytest.raises(TypeError, match="^calls.fetch: .*fetch has no parameter orderId to read the key from$"):
            evals.observe("calls.fetch", key_argument="orderId")(fetch)

    def test_a_key_argument_may_name_a_keyword_the_function_takes_through_kwargs(
        self, in_eval_trial, execute_action, returned
    ):
        def fetch(**kwargs): ...

        execute_action.return_value = returned(None)
        evals.observe("calls.fetch", key_argument="order_id")(fetch)(order_id="O1")

        assert execute_action.call_args.args[1]["key"] == "O1"
