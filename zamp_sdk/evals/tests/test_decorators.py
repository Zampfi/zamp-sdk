import pytest

from zamp_sdk import evals


def pages():
    yield 1


async def stream():
    yield 1


class TestDecorating:
    @pytest.mark.parametrize("decorator", [evals.external_call, evals.observe])
    @pytest.mark.parametrize("generator", [pages, stream])
    def test_a_generator_is_refused(self, decorator, generator):
        with pytest.raises(TypeError, match=f"^calls.pages: {generator.__qualname__} is a generator"):
            decorator("calls.pages")(generator)

    @pytest.mark.parametrize("decorator", [evals.external_call, evals.observe])
    def test_a_key_argument_that_is_not_a_parameter_is_refused(self, decorator):
        def fetch(order_id: str): ...

        with pytest.raises(TypeError, match="^calls.fetch: .*fetch has no parameter orderId to read the key from$"):
            decorator("calls.fetch", key_argument="orderId")(fetch)

    @pytest.mark.parametrize("decorator", [evals.external_call, evals.observe])
    def test_a_key_argument_may_name_a_keyword_the_function_takes_through_kwargs(self, decorator):
        def fetch(**kwargs): ...

        decorator("calls.fetch", key_argument="order_id")(fetch)
