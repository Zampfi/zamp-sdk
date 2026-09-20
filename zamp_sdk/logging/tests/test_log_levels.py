"""Levels and the user switch: which of a script's own log lines are shown."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import (
    LoggingConfig,
    LogLevel,
    bind_logging_config,
    configure_logging,
    emit_debug,
    emit_error,
    emit_info,
    emit_text,
)
from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.logging import log_control


@pytest.fixture
def execute():
    with patch.object(
        ActionExecutor,
        "execute",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = {"success": True}
        yield mock


class TestDefaultLevel:
    """INFO by default, so ``emit_debug`` is the line you can leave in the code permanently."""

    @pytest.mark.asyncio
    async def test_info_is_shown(self, execute):
        await emit_info("hello")
        assert execute.await_count == 1

    @pytest.mark.asyncio
    async def test_debug_is_hidden(self, execute):
        await emit_debug("noisy detail")
        assert execute.await_count == 0

    @pytest.mark.asyncio
    async def test_error_is_shown(self, execute):
        await emit_error("it broke")
        assert execute.await_count == 1

    @pytest.mark.asyncio
    async def test_emit_text_behaves_exactly_as_before(self, execute):
        """The helper every existing script uses must be untouched by levels existing."""
        await emit_text("step done")
        assert execute.await_count == 1

    @pytest.mark.asyncio
    async def test_a_suppressed_emit_reports_success(self, execute):
        """Callers are documented never to branch on the result, and a line that was
        deliberately not shown is not a failure to report."""
        result = await emit_debug("hidden")
        assert result.ok is True
        assert result.error is None


class TestConfiguring:
    @pytest.mark.asyncio
    async def test_lowering_the_level_reveals_debug(self, execute):
        configure_logging(level=LogLevel.DEBUG)
        await emit_debug("now visible")
        assert execute.await_count == 1

    @pytest.mark.asyncio
    async def test_level_accepts_a_name(self, execute):
        configure_logging(level="debug")
        await emit_debug("visible")
        assert execute.await_count == 1

    def test_an_unknown_level_is_rejected(self):
        """A typo here silently changes what the user sees, so it raises rather than
        falling back."""
        with pytest.raises(ValueError, match="not a known log level"):
            configure_logging(level="verbose")

    @pytest.mark.asyncio
    async def test_raising_the_level_hides_info(self, execute):
        configure_logging(level=LogLevel.ERROR)
        await emit_info("chatter")
        await emit_error("it broke")
        assert execute.await_count == 1

    @pytest.mark.asyncio
    async def test_disabling_silences_everything_including_errors(self, execute):
        configure_logging(enabled=False)
        await emit_info("x")
        await emit_error("y")
        assert execute.await_count == 0

    @pytest.mark.asyncio
    async def test_silencing_your_own_logs_leaves_auto_logging_alone(self, execute, monkeypatch):
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", "true")
        configure_logging(enabled=False)
        assert log_control.auto_action_logs_enabled() is True

    @pytest.mark.asyncio
    async def test_turning_auto_logging_off_leaves_your_own_logs_alone(self, execute):
        log_control.configure_auto_action_logs(False)
        await emit_info("still mine to send")
        assert execute.await_count == 1


class TestTheConfigTravelsWithTheRun:
    """A host binds the rules once; nothing has to read ambient state to find them.

    This is what makes the code-executor path safe. Reading an environment variable inside a
    workflow is a non-deterministic input — an emit there is a recorded command, so a variable
    that changed between the first run and a replay would change the command sequence and fail
    the run. Config carried on the workflow input is recorded in history instead.
    """

    @pytest.mark.asyncio
    async def test_a_bound_config_decides_the_rules(self, execute):
        bind_logging_config(LoggingConfig(level=LogLevel.DEBUG, auto_action_logs=True))

        await emit_debug("visible because the run was started in debug")
        assert execute.await_count == 1
        assert log_control.auto_action_logs_enabled() is True

    @pytest.mark.asyncio
    async def test_a_bound_config_is_not_read_from_the_environment(self, execute, monkeypatch):
        """The whole point on the workflow path: once bound, the environment is not consulted,
        so a variable changing under a replay cannot change what the run does."""
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", "true")
        bind_logging_config(LoggingConfig(auto_action_logs=False))

        assert log_control.auto_action_logs_enabled() is False

    @pytest.mark.asyncio
    async def test_binding_again_replaces_the_previous_run_s_rules(self, execute):
        """A worker serves many runs. Binding per run is what stops one run's settings
        reaching the next."""
        bind_logging_config(LoggingConfig(level=LogLevel.DEBUG))
        bind_logging_config(LoggingConfig())

        await emit_debug("the next run did not ask for debug")
        assert execute.await_count == 0

    @pytest.mark.asyncio
    async def test_a_script_can_still_override_what_it_was_given(self, execute):
        bind_logging_config(LoggingConfig(level=LogLevel.ERROR))
        configure_logging(level=LogLevel.DEBUG)

        await emit_debug("the script asked for more")
        assert execute.await_count == 1

    @pytest.mark.asyncio
    async def test_an_override_leaves_the_other_settings_alone(self, execute):
        """Changing one field must not quietly reset the rest to their defaults."""
        bind_logging_config(LoggingConfig(level=LogLevel.ERROR, auto_action_logs=True))
        configure_logging(enabled=False)

        config = log_control.current_logging_config()
        assert config.level is LogLevel.ERROR
        assert config.auto_action_logs is True
        assert config.enabled is False

    def test_the_defaults_are_the_shipped_behaviour(self):
        config = LoggingConfig()
        assert config.level is LogLevel.INFO
        assert config.enabled is True
        assert config.auto_action_logs is False, "off until the platform turns it on"

    def test_it_survives_a_round_trip_over_the_wire(self):
        """It travels on a Nexus request, so it has to serialize and come back the same."""
        original = LoggingConfig(level=LogLevel.DEBUG, enabled=False, auto_action_logs=True)
        assert LoggingConfig.model_validate(original.model_dump(mode="json")) == original

    def test_binding_nothing_is_allowed_and_means_the_defaults(self):
        """A workflow that started before the config field existed replays with no config. It
        gets the defaults, bound explicitly — not a fall-through to the environment, which a
        workflow must not read."""
        bind_logging_config(None)
        assert log_control.current_logging_config() == LoggingConfig()

    def test_binding_nothing_does_not_consult_the_environment(self, monkeypatch):
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", "true")
        bind_logging_config(None)
        assert log_control.auto_action_logs_enabled() is False

    def test_a_sandbox_script_assembles_its_config_from_the_environment(self, monkeypatch):
        """A plain process has no workflow input to carry the config, so it arrives a field per
        variable — the same style the channel context already travels in."""
        monkeypatch.setenv("ZAMP_LOG_LEVEL", "debug")
        monkeypatch.setenv("ZAMP_LOG_ENABLED", "false")
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", "1")

        assert log_control.current_logging_config() == LoggingConfig(
            level=LogLevel.DEBUG, enabled=False, auto_action_logs=True
        )

    def test_each_variable_is_read_on_its_own(self, monkeypatch):
        """Unlike the channel context, which is all-or-none because a partial one is no context
        at all, a field left unset here simply keeps its default."""
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", "true")

        assert log_control.current_logging_config() == LoggingConfig(auto_action_logs=True)

    @pytest.mark.parametrize("value", ["chatty", "", "20x"])
    def test_an_unreadable_level_costs_only_that_field(self, monkeypatch, value):
        """The platform sets these. A malformed one should cost the preference, not the run —
        and not the other fields either."""
        monkeypatch.setenv("ZAMP_LOG_LEVEL", value)
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", "true")

        config = log_control.current_logging_config()
        assert config.level is LogLevel.INFO
        assert config.auto_action_logs is True

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("true", True), ("1", True), ("false", False), ("0", False), ("nonsense", False)],
    )
    def test_a_flag_is_compared_not_cast(self, monkeypatch, raw, expected):
        """``bool("false")`` is True, which would turn the feature on for anyone trying to turn
        it off."""
        monkeypatch.setenv("ZAMP_AUTO_ACTION_LOGS", raw)
        assert log_control.current_logging_config().auto_action_logs is expected
