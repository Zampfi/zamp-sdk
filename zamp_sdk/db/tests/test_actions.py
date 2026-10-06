"""The single seam between the bridge and the platform.

Everything funnels through ``actions.call`` so the three rules below hold
everywhere rather than being re-decided at each call site.
"""

from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk.db.utils import actions
from zamp_sdk.db.utils.errors import AgentDbError

_EXECUTE = "zamp_sdk.db.utils.actions.ActionExecutor.execute"


class TestErrorTranslation:
    @pytest.mark.asyncio
    async def test_any_failure_becomes_an_agent_db_error(self):
        """Callers catch one type, whatever the executor raised."""
        with patch(_EXECUTE, new=AsyncMock(side_effect=RuntimeError("Action a FAILED: boom"))):
            with pytest.raises(AgentDbError):
                await actions.call("agent_db_execute_sql", {})

    @pytest.mark.asyncio
    async def test_metadata_survives_the_translation(self):
        with patch(
            _EXECUTE,
            new=AsyncMock(
                side_effect=RuntimeError("Action a FAILED: statement 2 failed [sqlstate=23505]: duplicate key")
            ),
        ):
            with pytest.raises(AgentDbError) as exc:
                await actions.call("agent_db_execute_sql", {})

        assert exc.value.sqlstate == "23505"
        assert exc.value.statement_index == 2

    @pytest.mark.asyncio
    async def test_an_agent_db_error_is_not_re_wrapped(self):
        original = AgentDbError("already ours", sqlstate="42703")

        with patch(_EXECUTE, new=AsyncMock(side_effect=original)):
            with pytest.raises(AgentDbError) as exc:
                await actions.call("agent_db_execute_sql", {})

        assert exc.value is original

    @pytest.mark.asyncio
    async def test_a_timeout_propagates_unwrapped(self):
        """A timeout is not a database error and must not be dressed up as one: the
        statement may well have committed, so a caller deciding whether to retry
        needs to see it for what it is."""
        with patch(_EXECUTE, new=AsyncMock(side_effect=TimeoutError("too slow"))):
            with pytest.raises(TimeoutError):
                await actions.call("agent_db_execute_sql", {})


class TestReportedFailure:
    """agent_db_execute_sql returns a failed body as a completed action whose result is
    ``{"results": [], "success": false, "error": ...}``. It must still raise, exactly as
    the action failing outright did, or a failed write reads as an empty success."""

    @pytest.mark.asyncio
    async def test_success_false_raises_with_the_platform_error(self):
        response = {
            "results": [],
            "success": False,
            "error": 'statement 1 failed [sqlstate=42703]: column "run_id" does not exist',
        }
        with patch(_EXECUTE, new=AsyncMock(return_value=response)):
            with pytest.raises(AgentDbError) as exc:
                await actions.call("agent_db_execute_sql", {})

        assert exc.value.sqlstate == "42703"
        assert exc.value.statement_index == 1
        assert 'column "run_id" does not exist' in exc.value.message

    @pytest.mark.asyncio
    async def test_success_false_without_a_message_still_raises(self):
        with patch(_EXECUTE, new=AsyncMock(return_value={"success": False})):
            with pytest.raises(AgentDbError, match="agent_db_execute_sql failed"):
                await actions.call("agent_db_execute_sql", {})

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response",
        [
            {"results": [{"rows": [{"id": 1}], "row_count": 1}], "success": True, "error": None},
            {"results": [{"rows": [{"id": 1}], "row_count": 1}]},
            {"datasets": []},
            None,
        ],
        ids=["success-true", "no-success-key", "other-action-shape", "none"],
    )
    async def test_anything_but_success_false_is_returned_unchanged(self, response):
        """Today's platform sends no ``success`` key at all, so this is a no-op until
        it does — the SDK can ship first."""
        with patch(_EXECUTE, new=AsyncMock(return_value=response)):
            assert await actions.call("agent_db_execute_sql", {}) is response


class TestGatewayEnvelope:
    """Under an ActionsHub host the gateway route hands back its envelope untouched,
    reporting a failure as a value. The bridge must read the result out of it and raise
    for a failure, as the API route does."""

    @pytest.mark.asyncio
    async def test_a_completed_envelope_yields_the_action_result(self):
        result = {"results": [{"rows": [{"id": 1}], "row_count": 1}]}
        envelope = {"id": "a-1", "status": "COMPLETED", "result": result, "error": None}
        with patch(_EXECUTE, new=AsyncMock(return_value=envelope)):
            assert await actions.call("agent_db_execute_sql", {}) == result

    @pytest.mark.asyncio
    async def test_a_failed_envelope_raises_with_its_error(self):
        envelope = {
            "id": "a-1",
            "status": "FAILED",
            "result": None,
            "error": "statement 0 failed [sqlstate=23505]: duplicate key",
        }
        with patch(_EXECUTE, new=AsyncMock(return_value=envelope)):
            with pytest.raises(AgentDbError) as exc:
                await actions.call("agent_db_execute_sql", {})

        assert exc.value.action_id == "a-1"
        assert exc.value.action_status == "FAILED"
        assert exc.value.sqlstate == "23505"

    @pytest.mark.asyncio
    async def test_a_completed_envelope_reporting_success_false_raises(self):
        envelope = {
            "id": "a-1",
            "status": "COMPLETED",
            "result": {"results": [], "success": False, "error": "statement 0 failed [sqlstate=42703]"},
            "error": None,
        }
        with patch(_EXECUTE, new=AsyncMock(return_value=envelope)):
            with pytest.raises(AgentDbError) as exc:
                await actions.call("agent_db_execute_sql", {})

        assert exc.value.sqlstate == "42703"


class TestWhatIsNeverSent:
    @pytest.mark.asyncio
    async def test_no_retry_or_timeout_overrides(self):
        """The platform's defaults encode reasoning about the seam. Overriding them
        client-side would replace that silently — and on a write path would add a
        retry the raw psycopg2 path never had."""
        with patch(_EXECUTE, new=AsyncMock(return_value={})) as executor:
            await actions.call("agent_db_execute_sql", {"statements": []})

        assert "action_retry_policy" not in executor.await_args.kwargs
        assert "action_start_to_close_timeout" not in executor.await_args.kwargs

    @pytest.mark.asyncio
    async def test_no_base_url_or_auth_token(self):
        """Identity rides in the env, not the call — ActionExecutor injects it."""
        with patch(_EXECUTE, new=AsyncMock(return_value={})) as executor:
            await actions.call("agent_db_execute_sql", {})

        assert "base_url" not in executor.await_args.kwargs
        assert "auth_token" not in executor.await_args.kwargs
