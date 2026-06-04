import json
from unittest.mock import AsyncMock, patch

import pytest

from zamp_sdk import (
    InputOption,
    UserInputResponse,
    multiple_choice,
    read_user_input,
    request_user_input,
    select_one,
    text_input,
)
from zamp_sdk.user_input.constants import (
    SDK_USER_INPUT_EXIT_CODE,
    SDK_USER_INPUT_MARKER,
)
from zamp_sdk.user_input.utils import (
    build_options,
    default_resume_command,
    strip_hitl_flag,
)


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

    def test_text_for_custom_then_text(self):
        r = UserInputResponse(responses=[{"response": {"custom_input": "hi"}}, {"response": {"text": "yo"}}])
        assert r.text_for(0) == "hi"
        assert r.text_for(1) == "yo"

    def test_out_of_range_returns_none(self):
        r = UserInputResponse(responses=[])
        assert r.selected_option_for(0) is None
        assert r.text_for(3) is None

    def test_response_without_nested_response_key(self):
        # falls back to the item itself when there's no "response" wrapper
        r = UserInputResponse(responses=[{"selected_option": "flat"}])
        assert r.selected_option_for(0) == "flat"


class TestStripHitlFlag:
    def test_strips_space_form(self):
        assert strip_hitl_flag(["main.py", "--hitl", "r.json", "--keep"]) == ["main.py", "--keep"]

    def test_strips_equals_form(self):
        assert strip_hitl_flag(["main.py", "--hitl=r.json"]) == ["main.py"]

    def test_noop_when_absent(self):
        assert strip_hitl_flag(["main.py", "input.json"]) == ["main.py", "input.json"]


class TestDefaultResumeCommand:
    def test_prepends_interpreter_and_strips_hitl(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["main.py", "--hitl", "old.json"])
        monkeypatch.setattr("sys.executable", "/usr/local/bin/python")
        assert default_resume_command() == ["/usr/local/bin/python", "main.py"]


class TestReadUserInputResponse:
    def test_none_when_no_flag(self):
        assert read_user_input(["main.py"]) is None

    def test_none_when_file_missing(self):
        assert read_user_input(["main.py", "--hitl", "/no/such/file.json"]) is None

    def test_reads_responses_object(self, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"responses": [{"response": {"selected_option": "yes"}}]}))
        out = read_user_input(["main.py", "--hitl", str(p)])
        assert isinstance(out, UserInputResponse)
        assert out.selected_option_for(0) == "yes"

    def test_reads_bare_list(self, tmp_path):
        p = tmp_path / "r.json"
        p.write_text(json.dumps([{"response": {"selected_option": "no"}}]))
        assert read_user_input(["main.py", "--hitl", str(p)]).selected_option_for(0) == "no"

    def test_equals_form_and_last_wins(self, tmp_path):
        first = tmp_path / "a.json"
        first.write_text(json.dumps({"responses": [{"response": {"selected_option": "stale"}}]}))
        last = tmp_path / "b.json"
        last.write_text(json.dumps({"responses": [{"response": {"selected_option": "fresh"}}]}))
        argv = ["main.py", "--hitl", str(first), f"--hitl={last}"]
        assert read_user_input(argv).selected_option_for(0) == "fresh"

    def test_malformed_json_returns_none(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert read_user_input(["main.py", "--hitl", str(p)]) is None


class TestRequestInput:
    @pytest.mark.asyncio
    async def test_posts_action_then_halts(self, monkeypatch, capsys):
        monkeypatch.setenv("ZAMP_CHANNEL_TYPE", "task")
        monkeypatch.setenv("ZAMP_CHANNEL_ID", "task-9")
        monkeypatch.setenv("ZAMP_RUN_ID", "run-9")
        monkeypatch.setattr("sys.argv", ["main.py", "--hitl", "prev.json"])
        monkeypatch.setattr("sys.executable", "/py")
        monkeypatch.setattr("os.getcwd", lambda: "/work")

        execute = AsyncMock(return_value={"success": True})
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit) as exc:
                await request_user_input([select_one("Proceed?", [("y", "Yes"), ("n", "No")])])

        assert exc.value.code == SDK_USER_INPUT_EXIT_CODE
        action_name, params = execute.call_args.args
        assert action_name == "request_user_input"
        assert params["requests"][0]["input_type"] == "select_one"
        assert params["context"] == {"channel_type": "task", "channel_id": "task-9", "run_id": "run-9"}
        # resume command has the interpreter prepended and the stale --hitl stripped
        assert params["resume"]["command"] == ["/py", "main.py"]
        assert params["resume"]["cwd"] == "/work"
        assert params["resume"]["run_id"] == "run-9"
        # the sentinel marker is printed for the plugin to detect
        assert SDK_USER_INPUT_MARKER in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_explicit_resume_command_override(self, monkeypatch):
        monkeypatch.setattr("os.getcwd", lambda: "/work")
        execute = AsyncMock(return_value=None)
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit):
                await request_user_input([text_input("q?")], resume_command=["python", "run.py", "--step", "2"])
        assert execute.call_args.args[1]["resume"]["command"] == ["python", "run.py", "--step", "2"]

    @pytest.mark.asyncio
    async def test_exits_nonzero_if_registration_fails(self, monkeypatch):
        execute = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("zamp_sdk.user_input.user_input.ActionExecutor.execute", execute):
            with pytest.raises(SystemExit) as exc:
                await request_user_input([text_input("q?")])
        # registration failure must NOT silently continue downstream steps
        assert exc.value.code == 1
