import json

import pytest

from zamp_sdk import (
    EscalationAnswer,
    escalate,
    escalation_from,
    parse_escalation,
    resume_script,
    run_workflow,
    select_one,
    text_input,
)
from zamp_sdk.context import ENV_EXECUTION_HOST, ExecutionHost
from zamp_sdk.escalation.constants import (
    ESCALATION_KEY,
    ESCALATION_WORKFLOW_PARAMS_KEY,
    MAX_DETAILS_BYTES,
    MAX_FILES,
    MAX_QUESTIONS,
    MAX_SUMMARY_CHARS,
    SDK_ESCALATION_MARKER,
)
from zamp_sdk.escalation.models import EscalationFile
from zamp_sdk.user_input.constants import SDK_USER_INPUT_EXIT_CODE


@pytest.fixture
def on_executor(monkeypatch):
    monkeypatch.setenv(ENV_EXECUTION_HOST, ExecutionHost.ACTIONS_HUB.value)


@pytest.fixture
def in_sandbox(monkeypatch):
    monkeypatch.delenv(ENV_EXECUTION_HOST, raising=False)
    monkeypatch.setenv("ZAMP_RUN_ID", "run-1")


def _marker_payload(out: str) -> dict:
    line = next(line for line in out.splitlines() if line.startswith(SDK_ESCALATION_MARKER))
    return json.loads(line[len(SDK_ESCALATION_MARKER) :])


@pytest.mark.usefixtures("on_executor")
class TestEscalateInAPhase:
    def test_returns_the_escalation_for_the_phase_to_return(self):
        result = escalate(
            "No base rate on file",
            details="Searched pages 1-4",
            files=["/home/agent/a.pdf", {"path": "/home/agent/b.pdf", "name": "b.pdf"}],
            questions=[select_one("Which line haul?", [("accept", "Accept"), ("flag", "Flag")])],
        )

        assert list(result) == [ESCALATION_KEY]
        sent = result[ESCALATION_KEY]
        assert sent["summary"] == "No base rate on file"
        assert sent["details"] == "Searched pages 1-4"
        assert sent["files"] == [{"path": "/home/agent/a.pdf"}, {"path": "/home/agent/b.pdf", "name": "b.pdf"}]
        assert sent["questions"][0]["options"] == [{"id": "accept", "label": "Accept"}, {"id": "flag", "label": "Flag"}]
        assert sent["requires_human"] is False
        # No post-action: the platform re-runs the same phase, which only it knows.
        assert "post_action" not in sent

    def test_without_questions_asks_the_summary_as_text(self):
        sent = escalate("What is the PRO number?")[ESCALATION_KEY]
        assert sent["questions"] == [text_input("What is the PRO number?")]

    def test_requires_human_overall_and_per_question(self):
        approve = {**select_one("Approve the payout?", [("yes", "Yes"), ("no", "No")]), "requires_human": True}
        sent = escalate("Payout ready", questions=[approve, text_input("Notes?")], requires_human=False)[ESCALATION_KEY]
        assert sent["questions"][0]["requires_human"] is True
        assert escalate("Payout ready", requires_human=True)[ESCALATION_KEY]["requires_human"] is True

    def test_accepts_an_escalation_file_and_a_schema(self):
        sent = escalate(
            "Pick the rate",
            files=[EscalationFile(path="/home/agent/rates.csv")],
            answer_schema={"type": "object", "properties": {"rate": {"type": "number"}}},
        )[ESCALATION_KEY]
        assert sent["files"] == [{"path": "/home/agent/rates.csv"}]
        assert sent["answer_schema"]["properties"]["rate"] == {"type": "number"}

    def test_run_workflow_post_action_is_kept(self):
        post_action = run_workflow("ApplyDecision", code_directory_path="audit/")
        sent = escalate("Blocked", post_action=post_action)[ESCALATION_KEY]
        assert sent["post_action"] == post_action

    def test_resume_script_post_action_is_refused(self):
        with pytest.raises(ValueError, match="run_workflow"):
            escalate("Blocked", post_action=resume_script())

    def test_post_action_without_a_phase_is_refused(self):
        with pytest.raises(ValueError, match="missing workflow_name"):
            escalate("Blocked", post_action={"type": "run_code_executor_workflow", "code_directory_path": "a/"})

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"summary": ""}, "summary"),
            ({"summary": "x" * (MAX_SUMMARY_CHARS + 1)}, "summary"),
            ({"summary": "s", "details": "x" * (MAX_DETAILS_BYTES + 1)}, "put longer material in a file"),
            ({"summary": "s", "files": ["/f"] * (MAX_FILES + 1)}, "files"),
            ({"summary": "s", "questions": [text_input("q")] * (MAX_QUESTIONS + 1)}, "questions"),
            ({"summary": "s", "questions": [{"input_type": "upload", "question": "q"}]}, "input_type"),
            ({"summary": "s", "questions": [{"input_type": "text", "question": " "}]}, "non-empty"),
            ({"summary": "s", "questions": [{"input_type": "select_one", "question": "q"}]}, "needs options"),
            (
                {"summary": "s", "questions": [{**text_input("q"), "requires_human": "yes"}]},
                "requires_human must be true or false",
            ),
            ({"summary": "s", "files": [{"path": "/f", "size": 3}]}, "Extra inputs"),
            ({"summary": "s", "files": [3]}, "a file is a path"),
        ],
    )
    def test_invalid_escalations_are_refused(self, kwargs, match):
        summary = kwargs.pop("summary")
        with pytest.raises(ValueError, match=match):
            escalate(summary, **kwargs)


@pytest.mark.usefixtures("in_sandbox")
class TestEscalateInAScript:
    def test_prints_the_marker_and_exits_for_a_re_run(self, capsys):
        with pytest.raises(SystemExit) as exc:
            escalate("No base rate on file", questions=[text_input("Which rate?")])

        assert exc.value.code == SDK_USER_INPUT_EXIT_CODE
        sent = _marker_payload(capsys.readouterr().out)
        assert sent["summary"] == "No base rate on file"
        assert sent["post_action"]["type"] == "resume_script"
        assert sent["post_action"]["run_id"] == "run-1"

    def test_keeps_a_resume_flag(self, capsys):
        with pytest.raises(SystemExit):
            escalate("Blocked", post_action=resume_script("--answer"))
        assert _marker_payload(capsys.readouterr().out)["post_action"]["command"][-1] == "--answer"

    def test_run_workflow_post_action_exits_with_an_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            escalate("Blocked", post_action=run_workflow("Next", code_directory_path="a/"))

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "resume_script" in captured.err
        assert SDK_ESCALATION_MARKER not in captured.out

    def test_invalid_escalation_exits_with_an_error(self, capsys):
        with pytest.raises(SystemExit) as exc:
            escalate("")
        assert exc.value.code == 1
        assert "escalate failed" in capsys.readouterr().err


ANSWERS = {
    "escalation_id": "esc-call-1",
    "note": "Took the billed amount",
    "value": {"rate": 271.63},
    "responses": [
        {
            "input_required": select_one("Which line haul?", [("accept", "Accept"), ("flag", "Flag")]),
            "response": {"type": "select_one", "selected_option": "accept"},
            "answered_by": "agent",
        },
        {
            "input_required": text_input("Notes?"),
            "response": {"type": "text", "text": "fine by me"},
            "answered_by": "human",
            "human_text": "fine by me",
        },
    ],
}


class TestReadingTheAnswers:
    def test_escalation_from_reads_the_next_phase_params(self):
        answer = escalation_from({"checkpoint": "x", ESCALATION_WORKFLOW_PARAMS_KEY: ANSWERS})

        assert isinstance(answer, EscalationAnswer)
        assert answer.escalation_id == "esc-call-1"
        assert answer.note == "Took the billed amount"
        assert answer.value == {"rate": 271.63}
        assert answer.selected_option_for(0) == "accept"
        assert answer.answered_by_for(0) == "agent"
        assert answer.human_text_for(0) is None
        assert answer.text_for(1) == "fine by me"
        assert answer.answered_by_for(1) == "human"
        assert answer.human_text_for(1) == "fine by me"
        assert answer.answered_by_for(5) is None

    @pytest.mark.parametrize("params", [{}, None, {ESCALATION_WORKFLOW_PARAMS_KEY: "nope"}])
    def test_escalation_from_is_none_on_a_first_run(self, params):
        assert escalation_from(params) is None

    def test_parse_escalation_reads_the_re_run_argument(self):
        answer = parse_escalation(json.dumps(ANSWERS))
        assert answer is not None
        assert answer.selected_option_for(0) == "accept"

    @pytest.mark.parametrize("value", [None, "", "not json", "[1, 2]"])
    def test_parse_escalation_is_none_without_answers(self, value):
        assert parse_escalation(value) is None
