"""Importing zamp_sdk must not load sqlalchemy or aiohttp; they load when first used.

Each check runs in a fresh interpreter, because other tests in this session may already have imported them.
"""

import subprocess
import sys
import textwrap


def _run(code: str) -> None:
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_importing_zamp_sdk_does_not_load_sqlalchemy_or_aiohttp():
    _run(
        """
        import sys
        import zamp_sdk
        assert "sqlalchemy" not in sys.modules
        assert "aiohttp" not in sys.modules
        assert "zamp_sdk.db.datasets" not in sys.modules
        """
    )


def test_db_names_still_reachable_from_zamp_sdk():
    _run(
        """
        import sys
        import zamp_sdk
        from zamp_sdk import AgentDbError, datasets
        from zamp_sdk.db import AgentDbError as DirectError, datasets as direct_datasets
        assert AgentDbError is DirectError and datasets is direct_datasets
        assert zamp_sdk.datasets is direct_datasets
        assert zamp_sdk.db is sys.modules["zamp_sdk.db"]
        assert "sqlalchemy" in sys.modules
        assert "AgentDbError" in vars(zamp_sdk)
        assert "datasets" in zamp_sdk.__all__ and "AgentDbError" in zamp_sdk.__all__
        """
    )


def test_unknown_name_still_raises_attribute_error():
    _run(
        """
        import zamp_sdk
        try:
            zamp_sdk.no_such_name
        except AttributeError:
            pass
        else:
            raise AssertionError("expected AttributeError")
        """
    )


def test_network_errors_still_mapped_after_aiohttp_loads():
    _run(
        """
        import aiohttp
        from zamp_sdk.action_executor.utils.http_client import HttpClient, HttpClientError
        client = HttpClient(base_url="http://x")
        for exc, want in ((aiohttp.ClientConnectionError("down"), "Network error"), (ValueError("x"), "Unexpected error")):
            try:
                client._handle_request_error(exc)
            except HttpClientError as err:
                assert str(err).startswith(want), str(err)
        """
    )


def test_db_utils_names_still_reachable():
    _run(
        """
        import sys
        from zamp_sdk.db.utils import AgentDbError
        assert "sqlalchemy" not in sys.modules
        from zamp_sdk.db.utils import Transaction, build_table, compile_statement
        from zamp_sdk.db.utils.transaction import Transaction as T
        assert Transaction is T and callable(build_table) and callable(compile_statement)
        assert "sqlalchemy" in sys.modules
        """
    )
