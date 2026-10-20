import json
from decimal import Decimal

import pytest

from zamp_sdk import (
    UserInputResponse,
    escalate,
    escalation_from,
    multiple_choice,
    parse_user_input,
    resume_script,
    run_workflow,
    select_one,
    text_input,
    user_input_from,
)
from zamp_sdk.context import ENV_EXECUTION_HOST, ExecutionHost
from zamp_sdk.escalation.constants import (
    ANSWERED_BY_AGENT,
    ANSWERED_BY_HUMAN,
    ANSWERED_BY_PARENT_AGENT,
    ESCALATION_KEY,
    ESCALATION_WORKFLOW_PARAMS_KEY,
    MAX_CONTEXT_BYTES,
    MAX_QUESTIONS,
    SDK_ESCALATION_MARKER,
)
from zamp_sdk.user_input.constants import SDK_USER_INPUT_EXIT_CODE, USER_INPUT_WORKFLOW_PARAMS_KEY


@pytest.fixture
def on_executor(monkeypatch):
    monkeypatch.setenv(ENV_EXECUTION_HOST, ExecutionHost.ACTIONS_HUB.value)


@pytest.fixture
def in_sandbox(monkeypatch):
    monkeypatch.delenv(ENV_EXECUTION_HOST, raising=False)
    monkeypatch.setenv("ZAMP_RUN_ID", "run-1")
    monkeypatch.setattr("sys.argv", ["main.py"])
    monkeypatch.setattr("sys.executable", "/py")
    monkeypatch.setattr("os.getcwd", lambda: "/work")


def _marker_payload(out: str) -> dict:
    line = next(line for line in out.splitlines() if line.startswith(SDK_ESCALATION_MARKER))
    return json.loads(line[len(SDK_ESCALATION_MARKER) :])


@pytest.mark.usefixtures("on_executor")
class TestEscalateInAPhase:
    @pytest.mark.asyncio
    async def test_returns_the_escalation_for_the_phase_to_return(self):
        questions = [
            select_one("Which line haul?", [("accept", "Accept"), ("flag", "Flag")]),
            multiple_choice("Which charges apply?", [("fuel", "Fuel"), ("detention", "Detention")]),
            text_input("What is the PRO number?"),
        ]

        result = await escalate(questions, context="Billed $271.63; no base rate on file")

        # The questions as the builders made them, and no post-action: the platform re-runs the
        # same phase, which only it knows.
        assert result == {ESCALATION_KEY: {"questions": questions, "context": "Billed $271.63; no base rate on file"}}

    @pytest.mark.asyncio
    async def test_without_context_none_is_sent(self):
        assert await escalate([text_input("What is the PRO number?")]) == {
            ESCALATION_KEY: {"questions": [text_input("What is the PRO number?")]}
        }

    @pytest.mark.asyncio
    async def test_context_up_to_the_cap_is_kept(self):
        context = "x" * MAX_CONTEXT_BYTES
        assert (await escalate([text_input("Which rate?")], context=context))[ESCALATION_KEY]["context"] == context

    @pytest.mark.asyncio
    async def test_requires_human_marks_every_question(self):
        questions = [
            select_one("Approve the payout?", [("yes", "Yes"), ("no", "No")]),
            {**text_input("Notes?"), "requires_human": False},
        ]

        sent = (await escalate(questions, requires_human=True))[ESCALATION_KEY]

        assert [q["requires_human"] for q in sent["questions"]] == [True, True]
        # Only per-question flags reach the platform, and the caller's dicts are left as they were.
        assert "requires_human" not in sent
        assert "requires_human" not in questions[0]
        assert questions[1]["requires_human"] is False

    @pytest.mark.asyncio
    async def test_a_question_can_require_a_human_on_its_own(self):
        approve = {**select_one("Approve the payout?", [("yes", "Yes"), ("no", "No")]), "requires_human": True}

        sent = (await escalate([approve, text_input("Notes?")]))[ESCALATION_KEY]

        assert sent["questions"] == [approve, text_input("Notes?")]

    @pytest.mark.asyncio
    async def test_a_run_workflow_post_action_is_kept(self):
        post_action = run_workflow("ApplyDecision", code_directory_path="audit/", workflow_params={"checkpoint": "ck"})

        sent = (await escalate([text_input("Which rate?")], post_action=post_action))[ESCALATION_KEY]

        assert sent["post_action"] == post_action

    @pytest.mark.asyncio
    async def test_a_resume_script_post_action_is_refused(self):
        with pytest.raises(
            ValueError, match=r"escalate: post_action must be run_workflow\(\.\.\.\) here, got resume_script"
        ):
            await escalate([text_input("Which rate?")], post_action=resume_script())

    @pytest.mark.asyncio
    async def test_a_post_action_that_names_no_phase_is_refused(self):
        with pytest.raises(ValueError, match="missing workflow_name"):
            await escalate(
                [text_input("Which rate?")],
                post_action={"type": "run_code_executor_workflow", "code_directory_path": "audit/"},
            )

    @pytest.mark.parametrize(
        ("requests", "kwargs", "match"),
        [
            ([], {}, "at least 1 item"),
            ([text_input("q")] * (MAX_QUESTIONS + 1), {}, f"at most {MAX_QUESTIONS} items"),
            ([text_input("q")], {"context": "x" * (MAX_CONTEXT_BYTES + 1)}, "put its path in context"),
            # The cap is in bytes: two bytes per character here.
            ([text_input("q")], {"context": "é" * (MAX_CONTEXT_BYTES // 2 + 1)}, "put its path in context"),
            ([{"input_type": "upload", "question": "q"}], {}, "input_type must be one of"),
            ([{"input_type": "text", "question": " "}], {}, "non-empty"),
            ([{"input_type": "select_one", "question": "q"}], {}, "needs options"),
            ([{**text_input("q"), "requires_human": "yes"}], {}, "requires_human must be true or false"),
            ([None], {}, "a question is a dict"),
        ],
    )
    @pytest.mark.asyncio
    async def test_an_invalid_escalation_is_refused(self, requests, kwargs, match):
        with pytest.raises(ValueError, match=match):
            await escalate(requests, **kwargs)


@pytest.mark.usefixtures("in_sandbox")
class TestEscalateInAScript:
    @pytest.mark.asyncio
    async def test_prints_the_marker_and_exits_for_a_re_run(self, capsys):
        with pytest.raises(SystemExit) as exc:
            await escalate([text_input("Which rate?")], context="No base rate on file")

        assert exc.value.code == SDK_USER_INPUT_EXIT_CODE
        # By default the same invocation is re-run, with the answers as its last argument.
        assert _marker_payload(capsys.readouterr().out) == {
            "questions": [text_input("Which rate?")],
            "context": "No base rate on file",
            "post_action": {"type": "resume_script", "command": ["/py", "main.py"], "cwd": "/work", "run_id": "run-1"},
        }

    @pytest.mark.asyncio
    async def test_keeps_a_resume_flag_and_marks_every_question(self, capsys):
        with pytest.raises(SystemExit) as exc:
            await escalate([text_input("Which rate?")], requires_human=True, post_action=resume_script("--answer"))

        assert exc.value.code == SDK_USER_INPUT_EXIT_CODE
        sent = _marker_payload(capsys.readouterr().out)
        assert sent["post_action"]["command"] == ["/py", "main.py", "--answer"]
        assert sent["questions"] == [{**text_input("Which rate?"), "requires_human": True}]

    @pytest.mark.parametrize(
        ("requests", "kwargs", "reason"),
        [
            (
                [text_input("Which rate?")],
                {"post_action": run_workflow("Next", code_directory_path="audit/")},
                "must be resume_script",
            ),
            ([], {}, "at least 1 item"),
            ([None], {}, "a question is a dict"),
            # Valid, but an option label that cannot be written as JSON.
            ([select_one("Which rate?", [("billed", Decimal("271.63"))])], {}, "not JSON serializable"),
        ],
    )
    @pytest.mark.asyncio
    async def test_any_failure_exits_1_without_the_marker(self, capsys, requests, kwargs, reason):
        with pytest.raises(SystemExit) as exc:
            await escalate(requests, **kwargs)

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "escalate failed" in captured.err
        assert reason in captured.err
        assert SDK_ESCALATION_MARKER not in captured.out


ANSWERS = {
    "escalation_id": "esc-call-1",
    "responses": [
        {
            "input_required": select_one("Which line haul?", [("accept", "Accept"), ("flag", "Flag")]),
            "response": {"type": "select_one", "selected_option": "flag"},
            "answered_by": ANSWERED_BY_HUMAN,
            "human_text": "this needs a second look",
        },
        {
            "input_required": text_input("What is the PRO number?"),
            "response": {"type": "text", "text": "PRO-1234"},
            "answered_by": ANSWERED_BY_AGENT,
        },
        {
            "input_required": text_input("Approved?"),
            "response": {"type": "text", "text": "yes"},
            "answered_by": ANSWERED_BY_PARENT_AGENT,
        },
    ],
}


class TestReadingTheAnswers:
    def test_escalation_from_reads_the_next_phase_params(self):
        answer = escalation_from({"checkpoint": "ck", ESCALATION_WORKFLOW_PARAMS_KEY: ANSWERS})

        assert isinstance(answer, UserInputResponse)
        assert answer.selected_option_for(0) == "flag"
        assert answer.answered_by_for(0) == "human"
        assert answer.human_text_for(0) == "this needs a second look"
        assert answer.text_for(1) == "PRO-1234"
        assert answer.answered_by_for(1) == "agent"
        assert answer.human_text_for(1) is None
        assert answer.answered_by_for(2) == "parent_agent"
        assert answer.answered_by_for(3) is None
        assert answer.human_text_for(3) is None

    @pytest.mark.parametrize("params", [{}, None, {ESCALATION_WORKFLOW_PARAMS_KEY: "nope"}])
    def test_escalation_from_is_none_on_a_first_run(self, params):
        assert escalation_from(params) is None

    def test_an_escalation_answer_and_a_user_input_answer_never_read_as_each_other(self):
        assert escalation_from({USER_INPUT_WORKFLOW_PARAMS_KEY: ANSWERS}) is None
        assert user_input_from({ESCALATION_WORKFLOW_PARAMS_KEY: ANSWERS}) is None

    def test_a_script_reads_the_answers_with_parse_user_input(self):
        answer = parse_user_input(json.dumps(ANSWERS))

        assert answer is not None
        assert answer.selected_option_for(0) == "flag"
        assert answer.answered_by_for(0) == "human"
        assert answer.human_text_for(0) == "this needs a second look"

    def test_a_request_user_input_answer_names_no_answerer(self):
        answer = UserInputResponse(responses=[{"response": {"selected_option": "yes"}}])

        assert answer.answered_by_for(0) is None
        assert answer.human_text_for(0) is None
