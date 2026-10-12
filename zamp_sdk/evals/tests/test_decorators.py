import pytest

from zamp_sdk import evals


def pages():
    yield 1


async def stream():
    yield 1


class TestDecorating:
    @pytest.mark.parametrize("decorator", [evals.external, evals.observe])
    @pytest.mark.parametrize("generator", [pages, stream])
    def test_a_generator_is_refused(self, decorator, generator):
        with pytest.raises(TypeError, match=f"^calls.pages: {generator.__qualname__} is a generator"):
            decorator("calls.pages")(generator)
