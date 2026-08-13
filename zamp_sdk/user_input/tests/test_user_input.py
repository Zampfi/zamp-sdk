import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import (
    AWAITING_USER_INPUT,
    InputOption,
    UserInputResponse,
    multiple_choice,
    parse_user_input,
    request_user_input,
    resume_script,
    run_workflow,
    select_one,
    text_input,
    user_input_from,
)
from zamp_sdk.context import ENV_EXECUTION_HOST, ExecutionHost
from zamp_sdk.user_input.constants import (
    POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
    SDK_USER_INPUT_EXIT_CODE,
    SDK_USER_INPUT_MARKER,
    USER_INPUT_WORKFLOW_PARAMS_KEY,
)

# resume_command_with is an internal helper (behind resume_script), not public API.
from zamp_sdk.user_input.utils import build_options, default_resume_command, resume_command_with


@pytest.fixture(autouse=True)
def _clear_zamp_env(monkeypatch):
    for var in (
        "ZAMP_CHANNEL_TYPE",
        "ZAMP_CHANNEL_ID",
        "ZAMP_STREAMING_ID",
        "ZAMP_MESSAGE_ID",
        "ZAMP_TOOL_CALL_ID",
        "ZAMP_RUN_ID",
    ):
        monkeypatch.delenv(var, raising=False)


class TestQuestionBuilders:
    def test_text_input(self):
        assert text_input("name?") == {"input_type": "text", "question": "name?"}

    def test_select_one_from_tuples(self):
        q = select_one("pick", [("a", "A"), ("b", "B")])
        assert q["input_type"] == "select_one"
        assert q["question"] == "pick"
        assert q["options"] == [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]

    def test_multiple_choice_from_tuples(self):
        q = multiple_choice("pick many", [("a", "A")])
        assert q["input_type"] == "multiple_choice"
        assert q["options"] == [{"id": "a", "label": "A"}]

    def test_options_accepts_input_option_and_dict(self):
        opts = build_options([InputOption(id="x", label="X"), {"id": "y", "label": "Y"}])
        assert opts == [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]

    def test_options_rejects_bad_shape(self):
        with pytest.raises(ValueError):
            build_options(["not-an-option"])


class TestUserInputResponse:
    def test_selected_option_for(self):
        r = UserInputResponse(responses=[{"response": {"selected_option": "yes"}}])
        assert r.selected_option_for(0) == "yes"

    def test_selected_options_for(self):
        r = UserInputResponse(responses=[{"response": {"selected_options": ["a", "c"]}}])
        assert r.selected_options_for(0) == ["a", "c"]
        # absent / out-of-range → empty list, never None
        assert r.selected_options_for(5) == []

    def test_text_for_custom_then_text(self):
        r = UserInputResponse(responses=[{"response": {"custom_input": "hi"}}, {"response": {"text": "yo"}}])
        assert r.text_for(0) == "hi"
        assert r.text_for(1) == "yo"

    def test_files_for(self):
        r = UserInputResponse(
            responses=[
                {
                    "response": {"text": ""},
                    "file_references": [{"path": "~/uploads/inv.xlsx", "name": "inv.xlsx"}],
                }
            ]
        )
        assert r.files_for(0) == [{"path": "~/uploads/inv.xlsx", "name": "inv.xlsx"}]
        # out-of-range → empty list
        assert r.files_for(2) == []

    def test_file_paths_for_resolves_home_relative(self):
        # The dashboard returns paths relative to the sandbox home root; they must
        # resolve to absolute /home/... so the script can open them.
        r = UserInputResponse(
            responses=[
                {
                    "response": {"text": ""},
                    "file_references": [
                        {"path": "idem_e68a7c/uploads/abc/report.pdf"},  # home-relative
                        {"path": "/tmp/already/abs.csv"},  # absolute → unchanged
                        {"path": "~/uploads/tilde.txt"},  # ~ → expanduser
                        {"name": "no-path-skip"},  # skipped
                    ],
                }
            ]
        )
        paths = r.file_paths_for(0)
        assert paths[0] == "/home/idem_e68a7c/uploads/abc/report.pdf"
        assert paths[1] == "/tmp/already/abs.csv"
        assert paths[2] == os.path.expanduser("~/uploads/tilde.txt")
        assert len(paths) == 3  # the path-less entry is dropped
        assert r.file_paths_for(9) == []

    def test_out_of_range_returns_none(self):
        r = UserInputResponse(responses=[])
        assert r.selected_option_for(0) is None
        assert r.text_for(3) is None
        assert r.files_for(0) == []

    def test_response_without_nested_response_key(self):
        # falls back to the item itself when there's no "response" wrapper
        r = UserInputResponse(responses=[{"selected_option": "flat"}])
        assert r.selected_option_for(0) == "flat"


class TestResumeCommandWith:
    def test_prepends_interpreter_and_appends_flag(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main.py"])
        monkeypatch.setattr("sys.executable", "/usr/local/bin/python")
        assert resume_command_with("--country") == ["/usr/local/bin/python", "main.py", "--country"]

    def test_threads_prior_answers_for_sequential(self, monkeypatch):
        # On a re-run, argv already carries the earlier answer — a fresh flag keeps it.
        monkeypatch.setattr("sys.argv", ["main.py", "--country", '{"responses": []}'])
        monkeypatch.setattr("sys.executable", "/py")
        assert resume_command_with("--tier") == [
            "/py",
            "main.py",
            "--country",
            '{"responses": []}',
            "--tier",
        ]

    def test_default_is_no_extra_flags(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main.py"])
        monkeypatch.setattr("sys.executable", "/py")
        assert default_resume_command() == ["/py", "main.py"]


class TestParseUserInput:
    def test_none_when_flag_unset(self):
        # First run: argparse default is None → "not answered yet".
        assert parse_user_input(None) is None
        assert parse_user_input("") is None

    def test_parses_responses_object(self):
        value = json.dumps({"responses": [{"response": {"selected_option": "yes"}}]})
        out = parse_user_input(value)
        assert isinstance(out, UserInputResponse)
        assert out.selected_option_for(0) == "yes"

    def test_parses_bare_list(self):
        value = json.dumps([{"response": {"selected_option": "no"}}])
        assert parse_user_input(value).selected_option_for(0) == "no"

    def test_parses_single_object(self):
        value = json.dumps({"response": {"text": "hi"}})
        assert parse_user_input(value).text_for(0) == "hi"

    def test_malformed_json_returns_none(self):
        assert parse_user_input("{not json") is None


class TestRequestInput:
    @pytest.mark.asyncio
    async def test_posts_action_then_halts(self, monkeypatch, capsys):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "task-9")
        monkeypatch.setenv("ZAMP_RUN_ID", "run-9")
        monkeypatch.setattr("sys.argv", ["main.py"])
        monkeypatch.setattr("sys.executable", "/py")
        monkeypatch.setattr("os.getcwd", lambda: "/work")

        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit) as exc:
                await request_user_input(
                    [select_one("Proceed?", [("y", "Yes"), ("n", "No")])],
                    post_action=resume_script("--proceed"),
                )

        assert exc.value.code == SDK_USER_INPUT_EXIT_CODE
        action_name, params = execute.call_args.args
        assert action_name == "request_user_input"
        assert params["requests"][0]["input_type"] == "select_one"
        assert params["context"] == {"channel_type": "task", "channel_id": "task-9", "run_id": "run-9"}
        # default post-action is resume_script; command ends with the answer flag
        pa = params["post_action"]
        assert pa["type"] == "resume_script"
        assert pa["command"] == ["/py", "main.py", "--proceed"]
        assert pa["cwd"] == "/work"
        assert pa["run_id"] == "run-9"
        # the sentinel marker is printed for the plugin to detect
        assert SDK_USER_INPUT_MARKER in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_defaults_resume_command_to_current_argv(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main.py"])
        monkeypatch.setattr("sys.executable", "/py")
        monkeypatch.setattr("os.getcwd", lambda: "/work")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit):
                await request_user_input([text_input("q?")])
        assert execute.call_args.args[1]["post_action"]["command"] == ["/py", "main.py"]

    @pytest.mark.asyncio
    async def test_explicit_resume_command_override(self, monkeypatch):
        monkeypatch.setattr("os.getcwd", lambda: "/work")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit):
                await request_user_input(
                    [text_input("q?")],
                    post_action=resume_script(command=["python", "run.py", "--step"]),
                )
        assert execute.call_args.args[1]["post_action"]["command"] == ["python", "run.py", "--step"]

    @pytest.mark.asyncio
    async def test_explicit_post_action_passthrough(self, monkeypatch):
        # An explicit post_action is sent as-is (run_id backfilled from context).
        monkeypatch.setenv("ZAMP_RUN_ID", "run-7")
        monkeypatch.setattr("os.getcwd", lambda: "/work")
        execute = AsyncMock(return_value=None)
        action = resume_script(command=["python", "main.py", "--x"], cwd="/custom")
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit):
                await request_user_input([text_input("q?")], post_action=action)
        pa = execute.call_args.args[1]["post_action"]
        assert pa == {
            "type": "resume_script",
            "command": ["python", "main.py", "--x"],
            "cwd": "/custom",
            "run_id": "run-7",
        }

    @pytest.mark.asyncio
    async def test_exits_nonzero_if_registration_fails(self, monkeypatch):
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit) as exc:
                await request_user_input([text_input("q?")])
        # registration failure must NOT silently continue downstream steps
        assert exc.value.code == 1


class TestRunWorkflowPostAction:
    def test_builds_the_run_code_executor_workflow_post_action(self):
        pa = run_workflow(
            "ApplyCategoryDecision",
            code_directory_path="invoice_process/",
            workflow_params={"checkpoint": "s3://ck.json"},
        )
        assert pa == {
            "type": POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
            "code_directory_path": "invoice_process/",
            "workflow_name": "ApplyCategoryDecision",
            "workflow_params": {"checkpoint": "s3://ck.json"},
        }

    def test_workflow_params_default_to_empty_and_are_copied(self):
        params = {"a": 1}
        pa = run_workflow("Next", code_directory_path="d/")
        assert pa["workflow_params"] == {}
        assert run_workflow("Next", code_directory_path="d/", workflow_params=params)["workflow_params"] is not params


class TestRequestInputFromAWorkflow:
    """The code-executor path: register the question, come back, let the phase end itself."""

    @pytest.fixture(autouse=True)
    def _on_the_workflow_host(self, monkeypatch):
        monkeypatch.setenv(ENV_EXECUTION_HOST, ExecutionHost.ACTIONS_HUB.value)

    @staticmethod
    def _post_action():
        return run_workflow(
            "ApplyCategoryDecision",
            code_directory_path="invoice_process/",
            workflow_params={"checkpoint": "s3://ck.json"},
        )

    @pytest.mark.asyncio
    async def test_registers_the_question_and_returns_nothing(self):
        """It comes back with no value — the phase ends itself with AWAITING_USER_INPUT."""
        execute = AsyncMock(return_value={})
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            returned = await request_user_input(
                [select_one("Category right?", [("y", "Yes"), ("n", "No")])],
                post_action=self._post_action(),
            )

        assert returned is None
        action_name, params = execute.call_args.args
        assert action_name == "request_user_input"
        assert params["requests"][0]["input_type"] == "select_one"
        assert params["post_action"]["workflow_name"] == "ApplyCategoryDecision"

    @pytest.mark.asyncio
    async def test_no_caller_context_is_sent(self):
        """channel_context is injected server-side from the execution token on this path."""
        execute = AsyncMock(return_value={})
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            await request_user_input([text_input("?")], post_action=self._post_action())

        assert set(execute.call_args.args[1]) == {"requests", "post_action"}

    @pytest.mark.asyncio
    async def test_a_script_post_action_is_rejected(self):
        """resume_script has no meaning here: a workflow is not re-run, its next phase is."""
        execute = AsyncMock(return_value={})
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(ValueError, match="run_workflow"):
                await request_user_input([text_input("?")], post_action=resume_script("--x"))

        execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_missing_post_action_is_rejected(self):
        """No default here — only the author knows which phase runs next."""
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", AsyncMock()):
            with pytest.raises(ValueError, match="got nothing"):
                await request_user_input([text_input("?")])

    @pytest.mark.asyncio
    async def test_a_post_action_that_says_nothing_to_run_is_rejected(self):
        """Rejected before the question is registered, so no unanswerable HITL is left behind."""
        execute = AsyncMock(return_value={})
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(ValueError, match="code_directory_path"):
                await request_user_input(
                    [text_input("?")],
                    post_action={
                        "type": POST_ACTION_RUN_CODE_EXECUTOR_WORKFLOW,
                        "workflow_name": "Next",
                    },
                )

        execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_failure_to_register_propagates(self):
        """A phase that ended quietly with no question recorded is worse than a failed one."""
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(RuntimeError, match="boom"):
                await request_user_input([text_input("?")], post_action=self._post_action())


class TestUserInputFrom:
    def test_reads_the_answer_the_platform_injected(self):
        answer = user_input_from(
            {
                "checkpoint": "s3://ck.json",
                USER_INPUT_WORKFLOW_PARAMS_KEY: {"responses": [{"response": {"selected_option": "no"}}]},
            }
        )
        assert answer is not None
        assert answer.selected_option_for(0) == "no"

    def test_none_when_the_phase_was_not_started_by_an_answer(self):
        assert user_input_from({"checkpoint": "s3://ck.json"}) is None
        assert user_input_from({}) is None
        assert user_input_from(None) is None

    def test_none_when_the_key_holds_something_other_than_a_payload(self):
        assert user_input_from({USER_INPUT_WORKFLOW_PARAMS_KEY: "not-a-dict"}) is None

    def test_the_halt_sentinel_is_what_a_phase_returns(self):
        assert AWAITING_USER_INPUT == {"_awaiting_user_input": True}
