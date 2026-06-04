import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import (
    InputOption,
    UserInputResponse,
    multiple_choice,
    parse_user_input,
    request_user_input,
    resume_command_with,
    select_one,
    text_input,
)
from zamp_sdk.user_input.constants import (
    SDK_USER_INPUT_EXIT_CODE,
    SDK_USER_INPUT_MARKER,
)
from zamp_sdk.user_input.utils import build_options, default_resume_command


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
                    resume_command=resume_command_with("--proceed"),
                )

        assert exc.value.code == SDK_USER_INPUT_EXIT_CODE
        action_name, params = execute.call_args.args
        assert action_name == "request_user_input"
        assert params["requests"][0]["input_type"] == "select_one"
        assert params["context"] == {"channel_type": "task", "channel_id": "task-9", "run_id": "run-9"}
        # resume command ends with the flag the answer JSON will land on
        assert params["resume"]["command"] == ["/py", "main.py", "--proceed"]
        assert params["resume"]["cwd"] == "/work"
        assert params["resume"]["run_id"] == "run-9"
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
        assert execute.call_args.args[1]["resume"]["command"] == ["/py", "main.py"]

    @pytest.mark.asyncio
    async def test_explicit_resume_command_override(self, monkeypatch):
        monkeypatch.setattr("os.getcwd", lambda: "/work")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit):
                await request_user_input([text_input("q?")], resume_command=["python", "run.py", "--step"])
        assert execute.call_args.args[1]["resume"]["command"] == ["python", "run.py", "--step"]

    @pytest.mark.asyncio
    async def test_exits_nonzero_if_registration_fails(self, monkeypatch):
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit) as exc:
                await request_user_input([text_input("q?")])
        # registration failure must NOT silently continue downstream steps
        assert exc.value.code == 1
