"""Levels and the user switch: which of a script's own log lines are shown."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import (
    LoggingConfig,
    LogLevel,
    TextContentBlock,
    bind_logging_config,
    configure_logging,
    emit_debug,
    emit_error,
    emit_info,
    emit_log,
    emit_text,
    emit_tool_result,
    emit_tool_use,
)
from zamp_sdk.action_executor import ActionExecutor
from zamp_sdk.capture import drain_log_capture, start_log_capture
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


class TestWhatCountsAsALevel:
    """A level is the word for it, but older forms still resolve — upgrading the SDK must not
    make a config that already exists invalid."""

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("info", LogLevel.INFO),
            ("INFO", LogLevel.INFO),
            (" Debug ", LogLevel.DEBUG),
            (LogLevel.ERROR, LogLevel.ERROR),
            # Levels used to be the stdlib numbers; a config written then still parses.
            (10, LogLevel.DEBUG),
            (20, LogLevel.INFO),
            (40, LogLevel.ERROR),
        ],
    )
    def test_it_resolves(self, given, expected):
        assert LogLevel(given) is expected
        assert LoggingConfig(level=given).level is expected

    @pytest.mark.parametrize("given", ["nope", "warning", 30, 1, True, None])
    def test_something_that_is_not_a_level_is_rejected(self, given):
        """Including 30 — WARNING does not exist yet, and silently picking a neighbour would
        hide the fact that the line will never be emitted at the level its author meant."""
        with pytest.raises(ValueError):
            LogLevel(given)

    def test_the_serialized_form_is_the_word(self):
        assert LoggingConfig().model_dump(mode="json")["level"] == "info"


class TestWhatReachesTheLogFile:
    """The script's own lines are captured into the step buffer, so the run's file keeps the
    author's own account of what happened — most of all the errors — alongside the action steps.
    """

    @pytest.fixture(autouse=True)
    def _capturing(self):
        start_log_capture()
        yield
        drain_log_capture()

    @pytest.mark.asyncio
    async def test_it_records_the_levelled_lines_and_not_the_progress_ones(self, execute):
        """``emit_text`` is shown and dropped — it is commentary for whoever is watching, and
        the file is read afterwards. ``emit_debug`` is absent for a different reason: the level
        gate, which governs both surfaces alike."""
        await emit_text("Step 1 of 3")
        await emit_info("Matched 87 of 90 rows")
        await emit_debug("cursor=abc123")
        await emit_error("Vendor API returned 502")

        captured = [(e["level"], e["content"]) for e in drain_log_capture()]

        assert captured == [
            ("info", "Matched 87 of 90 rows"),
            ("error", "Vendor API returned 502"),
        ]

    @pytest.mark.asyncio
    async def test_emit_text_is_shown_but_not_kept(self, execute):
        await emit_text("Step 1 of 3")

        assert execute.await_count == 1, "it still reaches the live message"
        assert drain_log_capture() == [], "and leaves nothing in the file"

    @pytest.mark.asyncio
    async def test_lowering_the_level_adds_the_debug_line(self, execute):
        configure_logging(level=LogLevel.DEBUG)

        await emit_debug("cursor=abc123")

        assert [e["content"] for e in drain_log_capture()] == ["cursor=abc123"]

    @pytest.mark.asyncio
    async def test_a_line_whose_delivery_failed_is_still_recorded(self, execute):
        """Captured before the send. A line that could not be delivered is exactly the one
        worth having in the file, and an author's error text most of all."""
        execute.side_effect = RuntimeError("no channel")

        await emit_error("Vendor API returned 502")

        assert [e["content"] for e in drain_log_capture()] == ["Vendor API returned 502"]

    @pytest.mark.asyncio
    async def test_emit_log_on_its_own_records_nothing(self, execute):
        """Only the named helpers record. ``emit_log`` is the escape hatch — it is also how a
        tool block is sent, and those must not reach the file."""
        await emit_log(TextContentBlock(content="raw escape hatch"))

        assert drain_log_capture() == []

    @pytest.mark.asyncio
    async def test_tool_blocks_are_not_captured_here(self, execute):
        """The action they describe is already an ``action`` step; recording both is the
        duplication that made the file unreadable."""
        block_id = await emit_tool_use("do_thing", input={"a": 1})
        await emit_tool_result(block_id, {"ok": True}, name="do_thing")

        assert drain_log_capture() == []
